"""Executor -- pure task runner with parallel execution.

Runs tasks in parallel within a batch using ThreadPoolExecutor.
Makes NO decisions, asks NO questions, has NO routing logic.
Supports running a full task list or a filtered subset (for phased execution).

Parallel execution is safe because:
- Each tool writes to a different state field (flight_options, hotel_options, etc.)
- list.append/extend is atomic under CPython's GIL
- Cache operations are thread-safe (dict access + isolated HTTP calls)
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.models.shared_state import SharedState
from app.tools.rag_tool import search_destinations
from app.tools.flights_tool import search_flights
from app.tools.hotels_tool import search_hotels
from app.tools.weather_tool import get_weather
from app.tools.poi_tool import search_pois

_MAX_WORKERS = 4


def run_executor(state: SharedState, tasks: list[dict] | None = None) -> None:
    """Execute a list of tasks in parallel. If tasks is None, uses state.task_list."""
    task_list = tasks if tasks is not None else state.task_list
    if not task_list:
        return

    total = len(task_list)
    print(f"           Executor: {total} tasks (parallel, {_MAX_WORKERS} workers)", flush=True)
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {
            pool.submit(_execute_single, state, task): (i, task)
            for i, task in enumerate(task_list)
        }
        for future in as_completed(futures):
            idx, task = futures[future]
            try:
                future.result()
            except Exception as exc:
                task_type = task.get("task", "?")
                print(f"           Executor [{idx+1}/{total}] {task_type} FAILED: {exc}", flush=True)

    print(f"           Executor: all {total} tasks done ({time.time()-t_start:.1f}s total)", flush=True)


def _execute_single(state: SharedState, task: dict) -> None:
    """Execute a single task (runs inside a thread)."""
    task_type = task.get("task", "")
    params = task.get("params", {})
    dest = task.get("destination_group", "")
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

    print(f"             {task_type}({dest}) done ({time.time()-t:.1f}s)", flush=True)
