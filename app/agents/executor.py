"""Executor -- pure task runner.

Runs tasks sequentially, stores results in SharedState.
Makes NO decisions, asks NO questions, has NO routing logic.
Supports running a full task list or a filtered subset (for phased execution).
"""

from __future__ import annotations

import time

from app.models.shared_state import SharedState
from app.tools.rag_tool import search_destinations
from app.tools.flights_tool import search_flights
from app.tools.hotels_tool import search_hotels
from app.tools.weather_tool import get_weather
from app.tools.poi_tool import search_pois


def run_executor(state: SharedState, tasks: list[dict] | None = None) -> None:
    """Execute a list of tasks. If tasks is None, uses state.task_list."""
    task_list = tasks if tasks is not None else state.task_list
    for i, task in enumerate(task_list):
        task_type = task.get("task", "")
        params = task.get("params", {})
        print(f"           Executor [{i+1}/{len(task_list)}] {task_type} ...", flush=True)
        t = time.time()

        if task_type == "rag_search":
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
