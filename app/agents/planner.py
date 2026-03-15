"""Planner -- the reasoning engine that converts goals into concrete tasks.

Two modes:

1. **Initial plan** (no prior verdicts): extracts constraints from the user
   prompt AND produces a full task plan in a single LLM call.
   Uses RAG knowledge (fetched before the LLM call) to ground destination choices.

2. **Delta plan** (after Verifier rejection): receives a repair category from
   the main loop. Generates ONLY the minimal corrective tasks.

SharedState is truth: whatever data exists in SharedState is reused.
"""

from __future__ import annotations

import json

from app.config import RAG_DISPLAY_CHARS_PLANNER, RAG_MAX_CHUNKS_PLANNER, RAG_TOP_K
from app.llm.client import call_llm
from app.models.shared_state import SharedState
from app.tools.rag_tool import search_destinations

_SYSTEM_PROMPT = """\
You are the Planner of an autonomous travel-planning agent.

You have TWO jobs in a single response:
1. Extract structured constraints from the user's free-form request.
2. Produce an ordered list of concrete, executable tasks.

Respond with a JSON object (no markdown):
{{
  "constraints": {{
    "origin": "city or airport code (null if unknown)",
    "destinations": ["candidate city names"],
    "start_date": "YYYY-MM-DD or null",
    "end_date": "YYYY-MM-DD or null",
    "flexible_dates": true/false,
    "season": "month or season or null",
    "duration_days": number or null,
    "budget_total": number or null,
    "budget_currency": "USD",
    "travelers": number or null,
    "pace": "relaxed / moderate / active / null",
    "interests": ["beaches", "culture", ...],
    "other_preferences": "any extra notes"
  }},
  "tasks": [
    {{ "task": "<task_type>", "params": {{ ... }}, "destination_group": "CityName" }}
  ]
}}

Available task types and params:

1. "rag_search"       -- {{"query": "<semantic search query>"}}
2. "search_flights"   -- {{"origin": "CityName", "destination": "CityName", "date": "YYYY-MM-DD", "return_date": "YYYY-MM-DD or null"}}
3. "search_hotels"    -- {{"destination": "CityName", "check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD", "adults": N}}
4. "get_weather"      -- {{"destination": "CityName", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}}
5. "search_pois"      -- {{"destination": "CityName"}}

IMPORTANT: "destination_group" must be set to the city name for each task.
This lets the system execute destination-by-destination and reason about
intermediate results (e.g. skip expensive destinations, pivot to cheaper ones).

KEY REASONING RULES:

- Tools accept ANY city name worldwide. Just pass the city name.

- When the user says a month/season + duration but no exact dates, YOU must
  pick concrete dates. Example: "May, 4 days" → "2026-05-09" to "2026-05-13".
  Today is {today}.

- When the user says a vague region ("Europe", "Southeast Asia"), use the
  RAG knowledge provided below to pick 3-4 specific cities that match.
  More cities = more comparison options for the user at zero extra LLM cost.
  Prefer a MIX of budget-friendly and popular destinations.
  If RAG knowledge doesn't cover the region, use your own knowledge.

- IMPORTANT: Only pick cities served by MAJOR COMMERCIAL AIRPORTS with
  scheduled airline service from the user's origin. Do NOT pick small towns
  (e.g. Montauk, Nags Head, Provincetown) that lack commercial flights.
  If the origin is New York, good beach destinations include: Miami, San Juan,
  Cancun, Nassau, Aruba, Punta Cana, Fort Lauderdale, etc.

- For each candidate city, generate search_flights, search_hotels,
  get_weather, and search_pois tasks with that city name.

- Do NOT re-fetch data types already collected (see "Already collected").
- If all data is already collected, return an EMPTY tasks array [].
- Keep the task list SHORT. Every task costs time and API quota.
- NEVER fabricate or guess prices, dates, or availability. Your job is only
  to produce the task plan — the Executor will fetch real data.
- For each destination, always include ALL 4 task types (search_flights,
  search_hotels, get_weather, search_pois) so we have complete data.
- Return ONLY valid JSON, no markdown.
"""


def run_planner(state: SharedState, repair_category: str | None = None) -> list[dict]:
    """Generate constraints + task list. Uses RAG to ground destination choices."""
    from datetime import date as _date
    today_str = _date.today().isoformat()
    system = _SYSTEM_PROMPT.replace("{today}", today_str)

    # Fetch RAG knowledge BEFORE calling the LLM (embedding call only, not an LLM call)
    if not state.destination_chunks and not repair_category:
        _prefetch_rag(state)

    context_parts = [f"User prompt: {state.raw_prompt}"]

    if state.constraints:
        context_parts.append(f"Current constraints: {json.dumps(state.constraints, default=str)}")
    else:
        context_parts.append(
            "No constraints extracted yet. You MUST extract them from the user prompt "
            "and return them in the 'constraints' field."
        )

    # RAG knowledge for grounded destination selection
    if state.destination_chunks:
        rag_summaries = [
            f"- {c.get('article_title', '?')}: {c.get('content', '')[:RAG_DISPLAY_CHARS_PLANNER]}"
            for c in state.destination_chunks[:RAG_MAX_CHUNKS_PLANNER]
        ]
        context_parts.append(
            "Destination knowledge from RAG (use to inform city choices):\n"
            + "\n".join(rag_summaries)
        )

    collected = []
    if state.flight_options:
        routes = list({f"{f.get('origin','?')}->{f.get('destination','?')}" for f in state.flight_options})
        collected.append(f"Flight options: {len(state.flight_options)} routes={routes[:5]} (DO NOT re-fetch)")
    if state.hotel_options:
        collected.append(f"Hotel options: {len(state.hotel_options)} (DO NOT re-fetch)")
    if state.weather_context:
        collected.append(f"Weather records: {len(state.weather_context)} (DO NOT re-fetch)")
    if state.poi_list:
        collected.append(f"POIs: {len(state.poi_list)} (DO NOT re-fetch)")

    if collected:
        context_parts.append("Already collected:\n  " + "\n  ".join(collected))
    else:
        context_parts.append("Nothing collected yet.")

    excluded = state.constraints.get("excluded_destinations", []) if state.constraints else []
    if excluded:
        context_parts.append(
            f"EXCLUDED DESTINATIONS (user already saw these, wants alternatives): "
            f"{', '.join(excluded)}.\n"
            f"Pick COMPLETELY DIFFERENT cities. Choose only cities served by major "
            f"commercial airports with scheduled flights from the origin."
        )

    if repair_category and state.verifier_verdicts:
        last_verdict = state.verifier_verdicts[-1]
        issues_json = json.dumps(last_verdict.get("issues", []), default=str)
        context_parts.append(f"REPAIR MODE: category = {repair_category}")
        context_parts.append(f"Verifier issues: {issues_json}")
        context_parts.append(
            "Only add tasks that directly fix the failing dimension. "
            "The Synthesizer will be re-run automatically."
        )

        if repair_category == "BUDGET":
            context_parts.append(
                "BUDGET repair: consider searching for cheaper dates/hotels/flights."
            )
        elif repair_category in ("ALIGNMENT", "MISSING_INFO", "GROUNDING"):
            context_parts.append(
                f"{repair_category} repair: likely fixable without new API calls -- return EMPTY tasks []."
            )

    user_prompt = "\n".join(context_parts)

    raw = call_llm(state, module="Planner", system_prompt=system, user_prompt=user_prompt)

    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            # New format: {"constraints": {...}, "tasks": [...]}
            new_constraints = result.get("constraints")
            if new_constraints:
                if state.constraints:
                    state.constraints.update(new_constraints)
                else:
                    state.constraints = new_constraints
            task_list = result.get("tasks", [])
            if not isinstance(task_list, list):
                task_list = [task_list]
        elif isinstance(result, list):
            # Legacy format: just a task array
            task_list = result
        else:
            task_list = []
    except json.JSONDecodeError:
        task_list = []

    # Ensure concrete dates on constraints and tasks so tools never see None.
    _backfill_dates_on_tasks(state, task_list)

    state.task_list = task_list
    return task_list


def _backfill_dates_on_tasks(state: SharedState, task_list: list[dict]) -> None:
    """Deterministically fill in missing dates on constraints and tasks.

    Some LLM responses may leave date fields as null/None even when duration
    and other info are present. This helper:
      1. Ensures state.constraints.start_date/end_date are set.
      2. Propagates those dates into search_flights/search_hotels/get_weather
         tasks that are missing or have falsy date fields.
    """
    from datetime import date as _date, timedelta as _timedelta

    if not isinstance(task_list, list) or not task_list:
        return

    constraints = state.constraints or {}
    start = constraints.get("start_date")
    end = constraints.get("end_date")
    duration = constraints.get("duration_days") or 5

    # If dates are missing, pick a concrete window based on today's date.
    if not start or not end:
        try:
            base = _date.today() + _timedelta(days=60)
        except Exception:
            base = _date.today()
        try:
            days = int(duration) if int(duration) > 0 else 5
        except Exception:
            days = 5
        start_dt = base
        end_dt = base + _timedelta(days=days)
        start = start_dt.isoformat()
        end = end_dt.isoformat()
        constraints["start_date"] = start
        constraints["end_date"] = end
        state.constraints = constraints

    # Propagate into tasks where dates are missing/None/empty.
    for task in task_list:
        if not isinstance(task, dict):
            continue
        params = task.get("params") or {}
        ttype = task.get("task")

        if ttype == "search_flights":
            if not params.get("date"):
                params["date"] = start
            if params.get("return_date") in (None, "", 0):
                params["return_date"] = end

        elif ttype == "search_hotels":
            if not params.get("check_in"):
                params["check_in"] = start
            if not params.get("check_out"):
                params["check_out"] = end

        elif ttype == "get_weather":
            if not params.get("start_date"):
                params["start_date"] = start
            if not params.get("end_date"):
                params["end_date"] = end

        task["params"] = params


def _prefetch_rag(state: SharedState) -> None:
    """Fetch RAG chunks before planning to ground destination choices.

    Uses only an embedding call (not an LLM call), so it doesn't consume
    the LLM budget.
    """
    try:
        search_destinations(state, query=state.raw_prompt, top_k=RAG_TOP_K)
    except Exception:
        pass


def get_destination_groups(task_list: list[dict]) -> list[str]:
    """Extract the ordered list of unique destination groups from the task list."""
    seen = set()
    groups = []
    for task in task_list:
        group = task.get("destination_group", "")
        if group and group not in seen:
            seen.add(group)
            groups.append(group)
    return groups


def split_tasks_by_destination(task_list: list[dict]) -> dict[str, list[dict]]:
    """Split the task list into groups keyed by destination_group.

    Tasks without a destination_group go into a "_general" bucket.
    """
    groups: dict[str, list[dict]] = {}
    for task in task_list:
        group = task.get("destination_group", "_general")
        groups.setdefault(group, []).append(task)
    return groups
