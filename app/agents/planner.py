"""Planner -- the reasoning engine that converts goals into concrete tasks.

Two modes:

1. **Initial plan** (no prior verdicts): builds a full plan from scratch.
   Always starts with extract_constraints if constraints are empty.

2. **Delta plan** (after Verifier rejection): receives a repair category from
   the main loop. Generates ONLY the minimal corrective tasks. Never
   re-runs tasks whose inputs did not change.

SharedState is truth: whatever data exists in SharedState is reused.
"""

from __future__ import annotations

import json

from app.llm.client import call_llm
from app.models.shared_state import SharedState

_SYSTEM_PROMPT = """\
You are the Planner of a travel-planning agent. Your job is to REASON about
the user's request and produce CONCRETE, executable tasks.

Given the user's constraints and what data has already been collected, produce
an ordered JSON array of tasks the Executor should run next.

Each task is a JSON object:
{
  "task": "<task_type>",
  "params": { ... }
}

Available task types and their expected params:

1. "extract_constraints"  -- params: {} (parse user prompt into structured fields)
2. "rag_search"           -- params: {"query": "<semantic search query>"}
3. "search_flights"       -- params: {"origin": "CityName", "destination": "CityName", "date": "YYYY-MM-DD", "return_date": "YYYY-MM-DD or null"}
4. "search_hotels"        -- params: {"destination": "CityName", "check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD", "adults": N}
5. "get_weather"          -- params: {"destination": "CityName", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
6. "search_pois"          -- params: {"destination": "CityName"}

KEY REASONING RULES:

- Tools accept ANY city name worldwide. You do NOT need coordinates -- the
  tools resolve city names to coordinates/IDs dynamically. Just pass the city
  name as "destination".

- When the user says a month/season + duration but no exact dates, YOU must
  pick concrete dates. Example: "May, 4 days" → pick "2026-05-09" to
  "2026-05-13" (a reasonable window in that month). Pick dates in the future.
  Today is {today}.

- When the user says a vague region ("Europe", "Southeast Asia"), YOU must
  pick 2-3 specific candidate cities that fit the user's interests/budget.
  Example: "Europe, best value" → Prague, Budapest, Athens.

- For each candidate city, generate separate search_flights, search_hotels,
  get_weather, and search_pois tasks with that city name and the dates you chose.

- Start with "extract_constraints" ONLY if constraints dict is empty.
- If it says rag_search was already done, you may use insights from RAG chunks
  to pick destination cities.
- Do NOT re-fetch data types already collected (see "Already collected" below).
- If flights, hotels, weather, and POIs are already collected, return an EMPTY array [].
- Keep the task list as SHORT as possible. Every task costs time.
- Return ONLY a JSON array, no markdown, no extra text.
"""


def run_planner(state: SharedState, repair_category: str | None = None) -> list[dict]:
    """Generate a task list. Avoids re-fetching data that already exists."""
    from datetime import date as _date
    today_str = _date.today().isoformat()
    system = _SYSTEM_PROMPT.replace("{today}", today_str)

    context_parts = [f"User prompt: {state.raw_prompt}"]

    if state.constraints:
        context_parts.append(f"Current constraints: {json.dumps(state.constraints, default=str)}")
    else:
        context_parts.append("No constraints extracted yet.")

    collected = []
    if state.destination_chunks:
        titles = list({c.get("article_title", "") for c in state.destination_chunks if c.get("article_title")})
        collected.append(f"RAG chunks: {len(state.destination_chunks)} about: {titles[:5]} (DO NOT re-fetch)")
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

    if repair_category and state.verifier_verdicts:
        last_verdict = state.verifier_verdicts[-1]
        issues_json = json.dumps(last_verdict.get("issues", []), default=str)
        context_parts.append(f"REPAIR MODE: category = {repair_category}")
        context_parts.append(f"Verifier issues: {issues_json}")
        context_parts.append(
            "Only add tasks that directly fix the failing dimension. "
            "The Synthesizer will be re-run automatically -- you do NOT need to add a synthesize task."
        )

        if repair_category == "BUDGET":
            context_parts.append(
                "BUDGET repair: consider searching for cheaper dates/hotels/flights. "
                "Only re-search if you change the search parameters (different dates, lower tier, etc)."
            )
        elif repair_category == "ALIGNMENT":
            context_parts.append(
                "ALIGNMENT repair: hotel/flight dates are inconsistent. "
                "This is likely fixable without new API calls -- return EMPTY array []."
            )
        elif repair_category == "MISSING_INFO":
            context_parts.append(
                "MISSING_INFO: return EMPTY array [] -- the main loop will ask the user."
            )
        elif repair_category == "GROUNDING":
            context_parts.append(
                "GROUNDING repair: claims are unsubstantiated. Return EMPTY array [] -- "
                "the Synthesizer will be re-run with stricter instructions."
            )

    user_prompt = "\n".join(context_parts)

    raw = call_llm(state, module="Planner", system_prompt=system, user_prompt=user_prompt)

    try:
        task_list = json.loads(raw)
        if not isinstance(task_list, list):
            task_list = [task_list]
    except json.JSONDecodeError:
        task_list = [{"task": "extract_constraints", "params": {}}] if not state.constraints else []

    state.task_list = task_list
    return task_list
