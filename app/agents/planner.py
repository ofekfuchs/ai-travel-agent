"""Planner -- converts the goal + current Shared State into an ordered task list.

The Planner *thinks* about what to do; the Executor *does* it.

Key optimizations:
- Explicitly tells the LLM what data is ALREADY collected (avoid re-fetching)
- Passes Verifier feedback so the Planner knows what to FIX specifically
- Keeps task lists small to minimize API calls
"""

from __future__ import annotations

import json

from app.llm.client import call_llm
from app.models.shared_state import SharedState

SYSTEM_PROMPT = """\
You are the Planner of a travel-planning agent.

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
3. "search_flights"       -- params: {"origin": "...", "destination": "...", "date": "YYYY-MM-DD", "return_date": "YYYY-MM-DD or null"}
4. "search_hotels"        -- params: {"destination": "...", "check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD", "adults": N}
5. "get_weather"          -- params: {"destination": "...", "latitude": N, "longitude": N, "start_date": "...", "end_date": "..."}
6. "search_pois"          -- params: {"destination": "...", "latitude": N, "longitude": N}

CRITICAL RULES:
- Start with "extract_constraints" ONLY if constraints dict is empty.
- Do NOT re-fetch data types that are already collected (see "Already collected" below).
- If flights, hotels, weather, and POIs are already collected, return an EMPTY array [].
- Only add new tasks for data that is genuinely MISSING.
- Keep the task list as SHORT as possible. Every task costs time and money.
- Return ONLY a JSON array, no markdown, no extra text.
"""


def run_planner(state: SharedState) -> list[dict]:
    """Generate a task list. Avoids re-fetching data that already exists."""
    context_parts = [f"User prompt: {state.raw_prompt}"]

    if state.constraints:
        context_parts.append(f"Current constraints: {json.dumps(state.constraints, default=str)}")
    else:
        context_parts.append("No constraints extracted yet.")

    collected = []
    if state.destination_chunks:
        collected.append(f"RAG chunks: {len(state.destination_chunks)} (DO NOT re-fetch)")
    if state.flight_options:
        collected.append(f"Flight options: {len(state.flight_options)} (DO NOT re-fetch)")
    if state.hotel_options:
        collected.append(f"Hotel options: {len(state.hotel_options)} (DO NOT re-fetch)")
    if state.weather_context:
        collected.append(f"Weather records: {len(state.weather_context)} (DO NOT re-fetch)")
    if state.poi_list:
        collected.append(f"POIs: {len(state.poi_list)} (DO NOT re-fetch)")

    if collected:
        context_parts.append("Already collected: " + ", ".join(collected))
    else:
        context_parts.append("Nothing collected yet.")

    if state.verifier_verdicts:
        last_verdict = state.verifier_verdicts[-1]
        context_parts.append(
            f"VERIFIER FEEDBACK (previous rejection): {json.dumps(last_verdict.get('issues', []), default=str)}"
        )
        context_parts.append(
            "The Synthesizer will handle fixing the rejected plan using existing data. "
            "Only add tasks here if NEW data is genuinely needed."
        )

    user_prompt = "\n".join(context_parts)

    raw = call_llm(state, module="Planner", system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)

    try:
        task_list = json.loads(raw)
        if not isinstance(task_list, list):
            task_list = [task_list]
    except json.JSONDecodeError:
        task_list = [{"task": "extract_constraints", "params": {}}] if not state.constraints else []

    state.task_list = task_list
    return task_list
