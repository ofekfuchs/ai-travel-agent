"""Executor -- pure task runner.

Runs the Planner's task list sequentially, stores results in SharedState.
Makes NO decisions, asks NO questions, has NO routing logic.
All city/coordinate resolution is handled dynamically inside the tools themselves.
"""

from __future__ import annotations

import json
import time

from app.llm.client import call_llm
from app.models.shared_state import SharedState
from app.tools.rag_tool import search_destinations
from app.tools.flights_tool import search_flights
from app.tools.hotels_tool import search_hotels
from app.tools.weather_tool import get_weather
from app.tools.poi_tool import search_pois

_EXTRACT_CONSTRAINTS_SYSTEM = """\
You are a constraint-extraction module.  Given a free-form travel request,
extract structured constraints as a JSON object with these fields (use null
for anything truly unspecified):

{
  "origin": "city or airport code",
  "destinations": ["candidate city/country names"],
  "start_date": "YYYY-MM-DD or null",
  "end_date": "YYYY-MM-DD or null",
  "flexible_dates": true/false,
  "season": "e.g. May, summer, winter, null",
  "duration_days": number or null,
  "budget_total": number or null,
  "budget_currency": "USD",
  "travelers": number or null,
  "pace": "relaxed / moderate / active / null",
  "interests": ["beaches", "culture", ...],
  "other_preferences": "any extra notes"
}

Return ONLY valid JSON, no markdown.
"""


def run_executor(state: SharedState) -> None:
    """Execute every task in the Planner's task list."""
    for i, task in enumerate(state.task_list):
        task_type = task.get("task", "")
        params = task.get("params", {})
        print(f"           Executor [{i+1}/{len(state.task_list)}] {task_type} ...", flush=True)
        t = time.time()

        if task_type == "extract_constraints":
            _extract_constraints(state)
        elif task_type == "rag_search":
            search_destinations(state, query=params.get("query", state.raw_prompt))
        elif task_type == "search_flights":
            search_flights(
                state,
                origin=params.get("origin", ""),
                destination=params.get("destination", ""),
                date=params.get("date", ""),
                return_date=params.get("return_date"),
            )
        elif task_type == "search_hotels":
            search_hotels(
                state,
                destination=params.get("destination", ""),
                check_in=params.get("check_in", ""),
                check_out=params.get("check_out", ""),
                adults=params.get("adults", 2),
            )
        elif task_type == "get_weather":
            get_weather(
                state,
                latitude=params.get("latitude", 0),
                longitude=params.get("longitude", 0),
                start_date=params.get("start_date", ""),
                end_date=params.get("end_date", ""),
                destination_name=params.get("destination", ""),
            )
        elif task_type == "search_pois":
            search_pois(
                state,
                latitude=params.get("latitude", 0),
                longitude=params.get("longitude", 0),
                destination_name=params.get("destination", ""),
            )

        print(f"                     done ({time.time()-t:.1f}s)", flush=True)


def _extract_constraints(state: SharedState) -> None:
    """Use 1 LLM call to parse the raw prompt into structured constraints."""
    raw = call_llm(
        state,
        module="Executor",
        system_prompt=_EXTRACT_CONSTRAINTS_SYSTEM,
        user_prompt=state.raw_prompt,
    )
    try:
        state.constraints = json.loads(raw)
    except json.JSONDecodeError:
        state.constraints = {"raw_intent": state.raw_prompt}
