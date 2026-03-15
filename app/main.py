"""Main FastAPI application -- Supervisor-driven agentic loop.

Architecture: The Supervisor is called at EVERY decision point, making this
a true agent rather than a static workflow:

  Supervisor → Plan → Execute(Phase1) → Supervisor → Execute(Phase2) → Synthesize → Verify
                                          ↑ observes partial results, decides:
                                            continue / pivot / synthesize

Key principles:
- Hard cap of 8 LLM calls per /api/execute invocation.
- Supervisor is called MULTIPLE TIMES -- it observes, reasons, and adapts.
- Planner extracts constraints + generates tasks in ONE call (saves budget).
- RAG grounds destination choices BEFORE planning.
- Executor runs in destination-group batches so Supervisor can observe.
- Delta replanning on rejection when budget allows.
"""

import json
import time
import traceback
import uuid

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Dict

from app.config import RAG_DISPLAY_CHARS_PLANNER, RAG_MAX_CHUNKS_GATE_B
from app.models.schemas import (
    AgentInfoPromptExample,
    AgentInfoPromptTemplate,
    AgentInfoResponse,
    ExecuteRequest,
    ExecuteResponse,
    Step,
    TeamInfoResponse,
    TeamInfoStudent,
)
from app.models.shared_state import SharedState
from app.llm.client import LLMCapReached
from app.agents.supervisor import run_supervisor
from app.agents.planner import run_planner, split_tasks_by_destination, get_destination_groups
from app.agents.executor import run_executor
from app.agents.synthesizer import run_synthesizer
from app.agents.verifier import run_verifier
from app.utils.trip_store import save_trip, save_session, log_execution

app = FastAPI(title="AI Travel Agent")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

DAILY_EXPENSES_ESTIMATE = 50
BUDGET_TOLERANCE = 1.05

MAX_SUPERVISOR_ROUNDS = 8
MAX_SESSIONS = 200
MAX_PROMPT_LENGTH = 1000

# In-memory session store for multi-turn conversation.
# Keyed by session_id, stores constraints + prompt from previous turns.
_session_memory: dict[str, dict] = {}


# ── GET /api/team_info ─────────────────────────────────────────────────────

@app.get("/api/team_info", response_model=TeamInfoResponse)
async def get_team_info() -> TeamInfoResponse:
    return TeamInfoResponse(
        group_batch_order_number="3_11",
        team_name="אופק עמרי ורות",
        students=[
            TeamInfoStudent(name="Ofek Fuchs", email="ofek.fuchs@campus.technion.ac.il"),
            TeamInfoStudent(name="Omri Lazover", email="omri.lazover@campus.technion.ac.il"),
        ],
    )


# ── GET /api/agent_info ────────────────────────────────────────────────────

@app.get("/api/agent_info", response_model=AgentInfoResponse)
async def get_agent_info() -> AgentInfoResponse:
    # Concrete example: real-looking steps and full_response as the agent actually returns
    example_steps = [
        Step(
            module="Supervisor",
            prompt={
                "system": "You are the Supervisor — the autonomous decision-making brain of a travel planning agent...",
                "user": "User prompt: Beach vacation in June from New York\nNo constraints extracted yet (first call).\nData collected so far: {\"rag_chunks\": 0, \"flights\": 0, \"hotels\": 0, \"weather\": 0, \"pois\": 0}\nLLM calls used: 0/12",
            },
            response={"content": '{"next_action": "plan", "reason": "Origin (New York) and season (June) provided, enough to create a task plan.", "clarification_question": null, "pivot_instructions": null}'},
        ),
        Step(
            module="Planner",
            prompt={
                "system": "You are the Planner of an autonomous travel-planning agent. You have TWO jobs in a single response: 1. Extract structured constraints...",
                "user": "User prompt: Beach vacation in June from New York\nDestination knowledge from RAG (use to inform city choices):\n- Miami: Beaches, nightlife, June is warm...\n- San Juan: Caribbean, beaches...\nNothing collected yet.",
            },
            response={"content": '{"constraints": {"origin": "New York", "destinations": ["Miami", "San Juan"], "season": "June", "duration_days": 7}, "tasks": [{"task": "search_flights", "params": {"origin": "New York", "destination": "Miami", "date": "2026-06-15", "return_date": "2026-06-22"}, "destination_group": "Miami"}, {"task": "search_hotels", "params": {"destination": "Miami", "check_in": "2026-06-15", "check_out": "2026-06-22"}, "destination_group": "Miami"}]}'},
        ),
        Step(
            module="Supervisor",
            prompt={
                "system": "You are the Supervisor...",
                "user": "Extracted constraints: {\"origin\": \"New York\", \"destinations\": [\"Miami\", \"San Juan\"]}\nData collected so far: {\"rag_chunks\": 5, \"flights\": 4, \"hotels\": 6, \"weather\": 1, \"pois\": 12}\nPer-destination observations:\n  Miami: flights=$320-$450 (4 options) hotels=$890-$1200 (6 options) min total=$1210 (60% of budget)\nRemaining destination groups in plan: [\"San Juan\"]\nLLM calls used: 2/12",
            },
            response={"content": '{"next_action": "continue", "reason": "Only Miami searched so far; one more destination (San Juan) will give better comparison.", "clarification_question": null, "pivot_instructions": null}'},
        ),
        Step(
            module="Supervisor",
            prompt={
                "system": "You are the Supervisor...",
                "user": "Data collected: flights=8, hotels=12, weather=2, pois=24\n  Miami: flights=$320-$450, hotels=$890-$1200\n  San Juan: flights=$280-$390, hotels=$720-$1100\nRemaining destination groups: []\nLLM calls used: 3/12",
            },
            response={"content": '{"next_action": "synthesize", "reason": "Two destinations with full data; enough to build tiered packages.", "clarification_question": null, "pivot_instructions": null}'},
        ),
        Step(
            module="Trip Synthesizer",
            prompt={
                "system": "You are the Trip Synthesizer. You receive REAL pricing data from tool APIs. Build 2-3 packages at different tiers...",
                "user": "User request: Beach vacation in June from New York\nConstraints: {\"origin\": \"New York\", \"destinations\": [\"Miami\", \"San Juan\"], \"budget_total\": 2000}\n=== Miami ===\nFlights (4 options, top 5): [{\"price\": 320, \"destination_city\": \"Miami\"}...]\nHotels (6 options): [{\"name\": \"Hotel A\", \"total_price\": 890}...]\n=== San Juan ===\nFlights (4 options)...\nHotels (6 options)...",
            },
            response={"content": '{"packages": [{"label": "Budget Pick", "destination": "San Juan", "date_window": "2026-06-15 to 2026-06-22", "flights": {"outbound": {"origin": "JFK", "destination": "SJU", "airline": "JetBlue", "departure": "2026-06-15T07:00:00", "arrival": "2026-06-15T11:30:00", "stops": 0}, "return": {"origin": "SJU", "destination": "JFK"}, "total_flight_cost": 280}, "hotel": {"name": "Hotel Caribe", "total_cost": 720, "per_night": 103, "check_in": "2026-06-15", "check_out": "2026-06-22"}, "weather_summary": "Warm, 28-32°C, chance of afternoon showers.", "itinerary": [{"day": 1, "date": "2026-06-15", "activities": ["Arrive San Juan", "Check in", "Beach"]}], "cost_breakdown": {"flights": 280, "hotel": 720, "daily_expenses_estimate": 350, "total": 1350}, "rationale": "Best value for a week in the Caribbean from NYC.", "assumptions": ["Prices per person for flights; 1 room for hotel."]}]}'},
        ),
        Step(
            module="Verifier",
            prompt={
                "system": "You are a pragmatic quality auditor of a travel-planning agent...",
                "user": "Draft plans: [{\"label\": \"Budget Pick\", \"destination\": \"San Juan\", \"cost_breakdown\": {\"total\": 1350}, ...}]\nUser constraints: {\"origin\": \"New York\", \"budget_total\": 2000}",
            },
            response={"content": '{"decision": "APPROVE", "issues": [], "warnings": ["Booking links are search URLs, not direct deeplinks."], "quality_notes": "Packages are grounded in provided data; totals within budget."}'},
        ),
    ]
    example = AgentInfoPromptExample(
        prompt="Beach vacation in June from New York",
        full_response=(
            '{"packages": [{"label": "Budget Pick", "destination": "San Juan", "date_window": "2026-06-15 to 2026-06-22", '
            '"flights": {"outbound": {"origin": "JFK", "destination": "SJU", "airline": "JetBlue", "departure": "2026-06-15T07:00:00", "arrival": "2026-06-15T11:30:00", "stops": 0}, '
            '"return": {"origin": "SJU", "destination": "JFK", "departure": "2026-06-22T14:00:00", "arrival": "2026-06-22T18:30:00"}, "total_flight_cost": 280}, '
            '"hotel": {"name": "Hotel Caribe", "total_cost": 720, "per_night": 103, "check_in": "2026-06-15", "check_out": "2026-06-22", "booking_url": "https://www.booking.com/..."}, '
            '"weather_summary": "Warm, 28-32°C. Chance of afternoon showers.", '
            '"itinerary": [{"day": 1, "date": "2026-06-15", "activities": ["Arrive San Juan", "Check in", "Beach"]}, {"day": 2, "date": "2026-06-16", "activities": ["Old San Juan", "Fort"]}], '
            '"cost_breakdown": {"flights": 280, "hotel": 720, "daily_expenses_estimate": 350, "total": 1350}, '
            '"rationale": "Best value for a week in the Caribbean from NYC.", "assumptions": ["Prices per person for flights; 1 room."]}]}'
        ),
        steps=example_steps,
    )
    return AgentInfoResponse(
        description=(
            "Autonomous Full-Package AI Travel Agent using a Supervisor-driven "
            "agentic loop (ReAct pattern). Given a free-form travel request, the "
            "Supervisor reasons at every decision point: it plans, observes partial "
            "results from flight/hotel/weather/POI tools, decides whether to continue "
            "searching, pivot destinations, or synthesize packages. Uses RAG (Pinecone "
            "with Wikivoyage) to ground destination choices, Supabase for caching and "
            "session persistence, and a pragmatic Verifier for quality assurance."
        ),
        purpose=(
            "Solve the problem of planning trips from vague, flexible intent. "
            "Users describe their ideal trip in plain language and receive complete, "
            "priced, bookable trip packages — no exact dates or destinations needed upfront."
        ),
        prompt_template=AgentInfoPromptTemplate(
            template=(
                "Describe your ideal trip in free-form text. Include any of: "
                "origin city, desired region or destination, rough dates or season, "
                "budget range, pace (relaxed / active), interests (beaches, culture, "
                "nightlife, food…), and number of travellers. Example: "
                "'Beach vacation in June from New York' or "
                "'1 week in Europe, best value, culture and food, from TLV'."
            )
        ),
        prompt_examples=[example],
    )


# ── GET /api/model_architecture ────────────────────────────────────────────

@app.get("/api/model_architecture")
async def get_model_architecture() -> FileResponse:
    png_path = Path(__file__).resolve().parent.parent / "architecture.png"
    return FileResponse(png_path, media_type="image/png")


# ── POST /api/execute  (Supervisor loop) ───────────────────────────────────

@app.post("/api/execute", response_model=ExecuteResponse)
async def execute_agent(request: ExecuteRequest) -> ExecuteResponse:
    """Supervisor-driven agentic loop.

    The Supervisor is called at EVERY decision point.  It observes the
    current state (partial tool results, prices vs budget, etc.) and
    decides what happens next.  This is the ReAct pattern:
      Reason → Act → Observe → Reason → Act → ...
    """
    # ── Input validation ──────────────────────────────────────────────
    prompt = request.prompt.strip() if request.prompt else ""
    if not prompt:
        return ExecuteResponse(
            status="error",
            error="Please describe your trip — where you want to go, when, and any preferences.",
            response=None,
            steps=[],
        )
    if len(prompt) > MAX_PROMPT_LENGTH:
        return ExecuteResponse(
            status="error",
            error=f"Prompt too long ({len(prompt)} characters). Please keep it under {MAX_PROMPT_LENGTH}.",
            response=None,
            steps=[],
        )

    try:
        session_id = request.session_id or str(uuid.uuid4())
        state = SharedState(
            raw_prompt=prompt,
            session_id=session_id,
            latest_user_message=prompt,
        )

        # ── Multi-turn: load previous session context ─────────────────
        prev_session = _session_memory.get(session_id) if request.session_id else None
        if prev_session:
            prev_prompt = prev_session.get("original_prompt", "")
            prev_constraints = prev_session.get("constraints", {})
            prev_history = prev_session.get("conversation_history", [])
            prev_destinations = prev_session.get("destinations_searched", [])
            prev_packages = prev_session.get("packages_offered", [])

            context_parts = [prev_prompt]
            if prev_destinations:
                context_parts.append(
                    f"Previously searched destinations: {', '.join(prev_destinations)}"
                )
            if prev_packages:
                pkg_desc = "; ".join(
                    f"{p['label']} in {p['destination']} (${p['total']:.0f})"
                    for p in prev_packages if p.get('destination')
                )
                context_parts.append(f"Packages already offered to user: {pkg_desc}")
            context_parts.append(f"User follow-up: {request.prompt}")

            state.raw_prompt = "\n\n".join(context_parts)
            if prev_constraints:
                state.constraints = prev_constraints.copy()

            wants_alternatives = _wants_different_destinations(request.prompt)
            if wants_alternatives and "destinations" in state.constraints:
                old_dests = state.constraints.pop("destinations", [])
                state.constraints["excluded_destinations"] = old_dests
                context_parts.insert(-1,
                    f"USER WANTS DIFFERENT destinations. Do NOT reuse: {', '.join(old_dests)}. "
                    f"Pick NEW cities with major commercial airports.")
                state.raw_prompt = "\n\n".join(context_parts)
                print(f"  -> Follow-up requests DIFFERENT destinations "
                      f"(excluded: {old_dests})", flush=True)

            state.conversation_history = prev_history + [
                {"role": "user", "content": request.prompt}
            ]
            print(f"\n  SESSION RESUMED: {session_id[:8]}... "
                  f"(prior constraints: {list(prev_constraints.keys()) if prev_constraints else 'none'}, "
                  f"prev destinations: {prev_destinations})", flush=True)
        else:
            state.conversation_history = [
                {"role": "user", "content": request.prompt}
            ]

        t_start = time.time()
        consecutive_empty_hotel_rounds = 0  # stop re-planning when hotels keep returning empty

        for round_num in range(MAX_SUPERVISOR_ROUNDS):
            print(f"\n{'='*60}", flush=True)
            print(f"  SUPERVISOR ROUND {round_num + 1}/{MAX_SUPERVISOR_ROUNDS}  "
                  f"(LLM calls: {state.llm_call_count}/{state.llm_call_cap})", flush=True)
            print(f"{'='*60}", flush=True)

            # ── Budget guard: force synthesis if running low on LLM calls ─
            # Synthesizer needs 1 call, Verifier needs 1 more. Reserve at
            # least 2 calls. If we already have flight+hotel data, skip the
            # Supervisor and go straight to synthesis.
            remaining = state.remaining_llm_calls()
            has_data = bool(state.flight_options and state.hotel_options)
            # If we're low on budget but have data, force synthesis.
            if remaining <= 2 and has_data and not state.draft_plans:
                print(f"  BUDGET GUARD: {remaining} calls left with data ready "
                      f"-- forcing synthesize", flush=True)
                action = "synthesize"
                reason = f"Deterministic: only {remaining} LLM calls remain, data is available."
                decision = {"next_action": action, "reason": reason}
            elif remaining <= 0:
                print("  LLM cap reached -- returning best-effort", flush=True)
                _save_session_memory(state)  # so follow-ups keep origin/constraints
                return _with_metadata(
                    _build_best_effort_response(state, "LLM budget exhausted."),
                    state, t_start)
            else:
                # Heuristic: if we have repeatedly tried multiple date ranges for the same
                # destination and always received empty hotel results, stop re-planning and
                # return a grounded best-effort message instead of looping.
                exhausted_dest, info = _find_exhausted_destination(state)
                if exhausted_dest and info:
                    tried_ranges = ", ".join(info["tried_ranges"])
                    print(
                        "  STOP: flights found but hotels empty for multiple date ranges "
                        f"for {exhausted_dest} -- returning best-effort", flush=True
                    )
                    _save_session_memory(state)
                    note = (
                        f"We found flights for {exhausted_dest} but could not find hotel "
                        f"availability in your budget for the date ranges we tried "
                        f"({tried_ranges}). Try different dates, a different destination, "
                        "or adjust your budget."
                    )
                    return _with_metadata(
                        _build_best_effort_response(state, note),
                        state,
                        t_start,
                    )
            if (state.flight_options and not state.hotel_options
                    and consecutive_empty_hotel_rounds >= 2):
                # Backwards-compatible guard: if flights exist but hotels have been empty
                # for several supervisor cycles (even without rich per-destination state),
                # fall back to a simpler best-effort message.
                print("  STOP: flights found but hotels empty for 2+ rounds "
                      "-- returning best-effort", flush=True)
                _save_session_memory(state)
                return _with_metadata(
                    _build_best_effort_response(
                        state,
                        "We found flights but could not find hotel availability for your dates/destination. "
                        "Try different dates or another destination."),
                    state, t_start)
            else:
                decision = run_supervisor(state)
                action = decision.get("next_action", "plan")
                reason = decision.get("reason", "")

                # Override: if Supervisor says "plan" but we already have
                # flight+hotel data and no remaining tasks, force synthesize.
                # This prevents the wasteful "plan → 0 tasks → plan → 0 tasks" loop.
                if (action == "plan"
                        and has_data
                        and not state.task_list
                        and round_num > 0):
                    print(f"  OVERRIDE: Supervisor chose 'plan' but data is ready "
                          f"and no tasks remain -- forcing synthesize", flush=True)
                    action = "synthesize"
                    reason += " [overridden: data ready, no remaining tasks]"
            print(f"  Supervisor -> {action} (calls: {state.llm_call_count})", flush=True)
            print(f"    reason: {reason}", flush=True)

            log_execution(
                session_id=state.session_id,
                round_num=round_num,
                action=action,
                reason=reason,
                data_snapshot={
                    "flights": len(state.flight_options),
                    "hotels": len(state.hotel_options),
                    "weather": len(state.weather_context),
                    "pois": len(state.poi_list),
                    "rag": len(state.destination_chunks),
                    "llm_calls": state.llm_call_count,
                },
            )

            # ── ask_clarification ──────────────────────────────────────
            if action == "ask_clarification":
                question = decision.get(
                    "clarification_question",
                    "Could you provide more details about your trip?"
                )
                # Save session so follow-up prompts inherit context
                _save_session_memory(state)
                state.conversation_history.append(
                    {"role": "assistant", "content": question}
                )
                clarification_response = json.dumps({
                    "type": "clarification",
                    "message": question,
                    "session_id": state.session_id,
                }, default=str)
                return _with_metadata(ExecuteResponse(
                    status="ok", error=None, response=clarification_response,
                    steps=[Step(**s) for s in state.steps],
                ), state, t_start)

            # ── finalize ───────────────────────────────────────────────
            if action == "finalize":
                return _with_metadata(_build_final_response(state), state, t_start)

            # ── plan / replan ──────────────────────────────────────────
            if action in ("plan", "replan", "pivot"):
                if not state.can_call_llm():
                    return _with_metadata(
                        _build_best_effort_response(state, "LLM budget exhausted."),
                        state, t_start)

                repair_cat = None
                if action == "replan" and state.verifier_verdicts:
                    repair_cat = _classify_rejection(state.verifier_verdicts[-1])
                    print(f"    Repair category: {repair_cat}", flush=True)

                if action == "pivot":
                    pivot_hint = decision.get("pivot_instructions", "")
                    if pivot_hint:
                        state.raw_prompt = f"{state.raw_prompt}\n\nAGENT NOTE: {pivot_hint}"
                        print(f"    Pivot: {pivot_hint}", flush=True)

                t1 = time.time()
                print(f"  Planner generating tasks (+RAG +constraints) ...", flush=True)
                run_planner(state, repair_category=repair_cat)
                print(f"    -> {len(state.task_list)} tasks ({time.time()-t1:.1f}s)", flush=True)
                if state.constraints:
                    print(f"    constraints: {json.dumps(state.constraints, default=str)[:200]}", flush=True)
                for t in state.task_list:
                    print(f"      * {t.get('task')}: {t.get('params', {})}", flush=True)

                # Execute FIRST destination group, then let Supervisor observe
                dest_groups = get_destination_groups(state.task_list)
                task_map = split_tasks_by_destination(state.task_list)

                if not state.task_list and action == "replan" and has_data:
                    print(f"  REPLAN produced 0 tasks but data exists "
                          f"-- retrying synthesize instead", flush=True)
                    state.draft_plans = []
                    action = "synthesize"
                elif dest_groups:
                    first_dest = dest_groups[0]
                    first_batch = task_map.get(first_dest, [])
                    general_tasks = task_map.get("_general", [])
                    all_first = general_tasks + first_batch

                    t2 = time.time()
                    hotel_count_before = len(state.hotel_options)
                    before_counts = _count_options_for_destination(state, first_dest)
                    print(f"  Executor Phase 1: '{first_dest}' ({len(all_first)} tasks) ...", flush=True)
                    run_executor(state, all_first)
                    print(f"    -> done ({time.time()-t2:.1f}s)", flush=True)
                    _print_data_summary(state)
                    _record_destination_attempts(state, first_dest, all_first, before_counts)
                    if any(t.get("task") == "search_hotels" for t in all_first):
                        if len(state.hotel_options) <= hotel_count_before:
                            consecutive_empty_hotel_rounds += 1
                        else:
                            consecutive_empty_hotel_rounds = 0

                    # Early feasibility check to avoid wasting LLM calls
                    early_feasibility = _feasibility_check(state)
                    if early_feasibility:
                        print(f"  EARLY GATE B: budget infeasible after Phase 1 "
                              f"(${early_feasibility['lower_bound']:.0f} > "
                              f"${early_feasibility['budget']:.0f})", flush=True)
                        _save_session_memory(state)
                        return _with_metadata(
                            _build_gate_b_response(state, early_feasibility), state, t_start)

                    # Remove executed tasks from task_list so Supervisor sees remaining
                    executed_ids = {id(t) for t in all_first}
                    state.task_list = [t for t in state.task_list
                                       if id(t) not in executed_ids
                                       and t.get("destination_group") != "_general"]
                else:
                    # No destination groups -- run all tasks
                    t2 = time.time()
                    print(f"  Executor running all {len(state.task_list)} tasks ...", flush=True)
                    run_executor(state)
                    print(f"    -> done ({time.time()-t2:.1f}s)", flush=True)
                    _print_data_summary(state)
                    state.task_list = []

                    # Early feasibility check to avoid wasting LLM calls
                    early_feasibility = _feasibility_check(state)
                    if early_feasibility:
                        print(f"  EARLY GATE B: budget infeasible "
                              f"(${early_feasibility['lower_bound']:.0f} > "
                              f"${early_feasibility['budget']:.0f})", flush=True)
                        _save_session_memory(state)
                        return _with_metadata(
                            _build_gate_b_response(state, early_feasibility), state, t_start)

                if action == "synthesize":
                    pass  # fall through to synthesize block below
                else:
                    # Loop back to Supervisor to observe and decide next step
                    continue

            # ── continue (execute remaining destination groups) ─────────
            if action == "continue":
                dest_groups = get_destination_groups(state.task_list)
                if dest_groups:
                    next_dest = dest_groups[0]
                    task_map = split_tasks_by_destination(state.task_list)
                    batch = task_map.get(next_dest, [])

                    t2 = time.time()
                    hotel_count_before = len(state.hotel_options)
                    before_counts = _count_options_for_destination(state, next_dest)
                    print(f"  Executor Phase N: '{next_dest}' ({len(batch)} tasks) ...", flush=True)
                    run_executor(state, batch)
                    print(f"    -> done ({time.time()-t2:.1f}s)", flush=True)
                    _print_data_summary(state)
                    _record_destination_attempts(state, next_dest, batch, before_counts)
                    if any(t.get("task") == "search_hotels" for t in batch):
                        if len(state.hotel_options) <= hotel_count_before:
                            consecutive_empty_hotel_rounds += 1
                        else:
                            consecutive_empty_hotel_rounds = 0

                    # Early feasibility check to avoid wasting LLM calls
                    early_feasibility = _feasibility_check(state)
                    if early_feasibility:
                        print(f"  EARLY GATE B: budget infeasible after Phase N "
                              f"(${early_feasibility['lower_bound']:.0f} > "
                              f"${early_feasibility['budget']:.0f})", flush=True)
                        _save_session_memory(state)
                        return _with_metadata(
                            _build_gate_b_response(state, early_feasibility), state, t_start)

                    state.task_list = [t for t in state.task_list
                                       if t.get("destination_group") != next_dest]
                else:
                    print(f"  No remaining tasks -- forcing synthesize", flush=True)
                    action = "synthesize"

                if action != "synthesize":
                    continue

            # ── synthesize ─────────────────────────────────────────────
            if action == "synthesize":
                if not state.flight_options and not state.hotel_options:
                    print(f"  NO PRICING DATA -- cannot synthesize", flush=True)
                    _save_session_memory(state)
                    return _with_metadata(
                        _build_no_data_response(state), state, t_start)

                feasibility = _feasibility_check(state)
                if feasibility:
                    print(f"  GATE B: budget infeasible (${feasibility['lower_bound']:.0f} "
                          f"> ${feasibility['budget']:.0f})", flush=True)
                    _save_session_memory(state)
                    return _with_metadata(
                        _build_gate_b_response(state, feasibility), state, t_start)

                # GATE C: Pre-synthesis data consistency check
                consistency_issues = _pre_synthesis_consistency_check(state)
                if consistency_issues:
                    print(f"  GATE C: data consistency issues", flush=True)
                    for iss in consistency_issues:
                        print(f"    ! {iss}", flush=True)
                    _save_session_memory(state)
                    return _with_metadata(
                        _build_no_data_response(state), state, t_start)

                if not state.can_call_llm():
                    _save_session_memory(state)
                    return _with_metadata(
                        _build_best_effort_response(state, "LLM budget exhausted."),
                        state, t_start)

                t3 = time.time()
                tight = _is_budget_tight(state)
                pkg_mode = "1 (tight)" if tight else "2-3 (tiered)"
                print(f"  Synthesizer building {pkg_mode} package(s) ...", flush=True)
                run_synthesizer(state, tight_budget=tight)
                print(f"    -> {len(state.draft_plans)} packages ({time.time()-t3:.1f}s)", flush=True)

                # Verify
                if not state.can_call_llm():
                    print("  No budget for Verifier -- returning packages as-is", flush=True)
                    _save_session_memory(state)
                    return _with_metadata(
                        _build_final_response(state), state, t_start)

                t4 = time.time()
                print(f"  Verifier auditing ...", flush=True)
                verdict = run_verifier(state)
                vdecision = verdict.get("decision", "REJECT")
                print(f"    -> {vdecision} ({time.time()-t4:.1f}s)", flush=True)
                if verdict.get("issues"):
                    for iss in verdict["issues"]:
                        print(f"      ! {iss}", flush=True)
                if verdict.get("warnings"):
                    for w in verdict["warnings"]:
                        print(f"      ~ {w}", flush=True)

                if vdecision == "APPROVE":
                    print(f"\n  APPROVED in {time.time()-t_start:.1f}s total", flush=True)
                    _save_session_memory(state)
                    return _with_metadata(
                        _build_final_response(state), state, t_start)

                # Rejected -- loop back to Supervisor to decide replan
                if not state.can_call_llm():
                    print(f"  REJECTED, no LLM budget for replan -- best-effort", flush=True)
                    _save_session_memory(state)
                    repair = _classify_rejection(verdict)
                    return _with_metadata(
                        _build_rejection_response(state, verdict, repair),
                        state, t_start)

                print(f"  REJECTED -- Supervisor will decide next step", flush=True)
                continue

        # Exhausted all rounds
        print(f"  Max supervisor rounds reached -- returning best-effort", flush=True)
        _save_session_memory(state)
        return _with_metadata(
            _build_best_effort_response(state, "Agent loop exhausted."),
            state, t_start)

    except LLMCapReached as exc:
        print(f"\n  LLM CAP REACHED (safety net): {exc}", flush=True)
        _save_session_memory(state)  # so follow-ups keep origin/destinations/constraints
        return _with_metadata(
            _build_best_effort_response(state, str(exc)), state, t_start)

    except Exception as exc:
        print(f"\n  ERROR: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return ExecuteResponse(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            response=None,
            steps=[Step(**s) for s in state.steps],
        )


_ALTERNATIVE_KEYWORDS = {
    "different", "other", "alternative", "new", "else", "more",
    "another", "elsewhere", "somewhere", "instead",
}

def _wants_different_destinations(prompt: str) -> bool:
    """Detect if a follow-up prompt asks for alternative destinations."""
    lower = prompt.lower()
    for kw in _ALTERNATIVE_KEYWORDS:
        if kw in lower:
            return True
    return False


def _with_metadata(resp: ExecuteResponse, state: SharedState, t_start: float) -> ExecuteResponse:
    """Attach session_id, LLM call count and elapsed time to any response."""
    resp.session_id = state.session_id
    resp.llm_calls_used = state.llm_call_count
    resp.elapsed_seconds = round(time.time() - t_start, 1)
    return resp


def _print_data_summary(state: SharedState) -> None:
    print(f"    data: flights={len(state.flight_options)} "
          f"hotels={len(state.hotel_options)} weather={len(state.weather_context)} "
          f"POIs={len(state.poi_list)} RAG={len(state.destination_chunks)}", flush=True)


def _count_options_for_destination(state: SharedState, destination: str) -> dict[str, int]:
    """Return counts of flights/hotels currently stored for a given destination city."""
    dest_norm = (destination or "").strip().lower()
    flights = sum(
        1
        for f in state.flight_options
        if (f.get("destination_city") or f.get("destination") or "").strip().lower() == dest_norm
    )
    hotels = sum(
        1
        for h in state.hotel_options
        if (h.get("destination_city") or h.get("city") or "").strip().lower() == dest_norm
    )
    return {"flights": flights, "hotels": hotels}


def _record_destination_attempts(
    state: SharedState,
    destination: str,
    tasks: list[dict],
    before_counts: dict[str, int],
) -> None:
    """Update in-memory search history for a destination after executing tasks.

    Tracks which date ranges were attempted and whether flights/hotels came
    back empty for those ranges. This is used to justify early best-effort exits
    after multiple failed attempts for the same destination.
    """
    dest_key = (destination or "").strip()
    if not dest_key:
        return

    after_counts = _count_options_for_destination(state, dest_key)

    entry = state.destination_search_state.setdefault(
        dest_key,
        {
            "date_ranges_tried": set(),
            "hotel_empty_ranges": set(),
            "flight_empty_ranges": set(),
        },
    )

    for t in tasks:
        params = t.get("params") or {}
        task_type = t.get("task")

        if task_type == "search_hotels":
            ci = params.get("check_in")
            co = params.get("check_out")
            key = f"{ci}:{co}"
            entry["date_ranges_tried"].add(key)
            if after_counts["hotels"] <= before_counts.get("hotels", 0):
                entry["hotel_empty_ranges"].add(key)

        if task_type == "search_flights":
            dt = params.get("date")
            rd = params.get("return_date")
            key = f"{dt}:{rd}"
            entry["date_ranges_tried"].add(key)
            if after_counts["flights"] <= before_counts.get("flights", 0):
                entry["flight_empty_ranges"].add(key)


def _find_exhausted_destination(state: SharedState, max_date_variants: int = 3) -> tuple[str, dict] | tuple[None, None]:
    """Return a destination whose flexible date search space appears exhausted.

    Heuristic: a destination is considered 'exhausted' if:
      - At least `max_date_variants` distinct date ranges were tried, AND
      - All of those ranges produced no hotels, AND
      - At least one flight option exists for that destination (so the route is viable).
    """
    for dest, entry in state.destination_search_state.items():
        tried = entry.get("date_ranges_tried", set())
        hotel_empty = entry.get("hotel_empty_ranges", set())
        if not tried:
            continue
        if len(hotel_empty) < max_date_variants:
            continue

        counts = _count_options_for_destination(state, dest)
        if counts["flights"] > 0 and counts["hotels"] == 0:
            return dest, {
                "tried_ranges": sorted(hotel_empty),
                "attempt_count": len(hotel_empty),
            }

    return None, None


# ═══════════════════════════════════════════════════════════════════════════
#   No-data response
# ═══════════════════════════════════════════════════════════════════════════

def _build_no_data_response(state: SharedState) -> ExecuteResponse:
    """Return when pricing tools returned no results."""
    _save_session_memory(state)
    dests = state.constraints.get("destinations", []) if state.constraints else []
    dest_str = ", ".join(dests) if dests else "your destination"

    msg = (
        f"I wasn't able to find flight or hotel pricing data for {dest_str} "
        f"with the given dates. This can happen if:\n"
        f"  - The API is temporarily unavailable\n"
        f"  - The dates are too far in the future\n\n"
        f"Could you try:\n"
        f"  - Slightly different dates\n"
        f"  - Or let me know your preferences and I'll suggest alternatives!"
    )

    result = {
        "status": "no_pricing_data",
        "message": msg,
        "constraints_extracted": state.constraints,
        "rag_knowledge_found": len(state.destination_chunks),
        "llm_calls_used": state.llm_call_count,
    }
    return ExecuteResponse(
        status="ok", error=None,
        response=json.dumps(result, indent=2, default=str),
        steps=[Step(**s) for s in state.steps],
    )


# ═══════════════════════════════════════════════════════════════════════════
#   GATE B: Feasibility check (deterministic, zero LLM calls)
# ═══════════════════════════════════════════════════════════════════════════

def _feasibility_check(state: SharedState) -> dict | None:
    """Compute a lower-bound cost from real tool data and compare to budget.

    Returns None if feasible (or no budget constraint), else a dict with
    the computed lower bound and gap info.
    """
    budget = state.constraints.get("budget_total") if state.constraints else None
    if not budget:
        return None

    try:
        budget_num = float(budget)
    except (ValueError, TypeError):
        return None

    cheapest_flight = _cheapest_price(state.flight_options, "price")
    cheapest_hotel = _cheapest_price(state.hotel_options, "total_price")

    if cheapest_flight is None and cheapest_hotel is None:
        return None

    travelers = state.constraints.get("travelers") or 1
    try:
        travelers = max(1, int(travelers))
    except (ValueError, TypeError):
        travelers = 1

    # Flight prices are per-person roundtrip — multiply by travelers
    flight_cost = (cheapest_flight or 0) * travelers
    hotel_cost = cheapest_hotel or 0

    duration = state.constraints.get("duration_days") or 4
    try:
        duration = int(duration)
    except (ValueError, TypeError):
        duration = 4

    daily_expenses = DAILY_EXPENSES_ESTIMATE * duration * travelers
    lower_bound = flight_cost + hotel_cost + daily_expenses

    if lower_bound > budget_num * BUDGET_TOLERANCE:
        return {
            "lower_bound": lower_bound,
            "cheapest_roundtrip_flight": flight_cost,
            "cheapest_flight_per_person": cheapest_flight or 0,
            "travelers": travelers,
            "hotel_total": hotel_cost,
            "daily_expenses": daily_expenses,
            "duration": duration,
            "budget": budget_num,
            "gap_pct": round((lower_bound - budget_num) / budget_num * 100, 1),
            "dominant_cost": "flights" if flight_cost > hotel_cost else "hotels",
        }

    return None


def _cheapest_price(options: list[dict], key: str) -> float | None:
    prices = [o.get(key) for o in options if o.get(key)]
    if not prices:
        return None
    try:
        return min(float(p) for p in prices)
    except (ValueError, TypeError):
        return None


def _is_budget_tight(state: SharedState) -> bool:
    """Returns True if lower-bound cost is within 85%-105% of budget."""
    budget = state.constraints.get("budget_total") if state.constraints else None
    if not budget:
        return False
    try:
        budget_num = float(budget)
    except (ValueError, TypeError):
        return False

    travelers = state.constraints.get("travelers") or 1
    try:
        travelers = max(1, int(travelers))
    except (ValueError, TypeError):
        travelers = 1

    cheapest_flight = _cheapest_price(state.flight_options, "price")
    cheapest_hotel = _cheapest_price(state.hotel_options, "total_price")
    flight_cost = (cheapest_flight or 0) * travelers
    hotel_cost = cheapest_hotel or 0
    duration = state.constraints.get("duration_days") or 4
    try:
        duration = int(duration)
    except (ValueError, TypeError):
        duration = 4
    lower_bound = flight_cost + hotel_cost + (DAILY_EXPENSES_ESTIMATE * duration * travelers)

    return lower_bound > budget_num * 0.85


# ═══════════════════════════════════════════════════════════════════════════
#   GATE C: Pre-synthesis data consistency check (deterministic, zero LLM)
# ═══════════════════════════════════════════════════════════════════════════

def _pre_synthesis_consistency_check(state: SharedState) -> list[str]:
    """Check data consistency before synthesis. Returns list of issues.

    Only checks high-signal conditions that would cause synthesis to fail:
    - No overlapping destinations between flights and hotels
    - Hotels missing names (unusable records)
    - Flight arrival after hotel check-in for same destination
    """
    issues: list[str] = []

    if not state.flight_options or not state.hotel_options:
        return issues

    flight_dests = {
        (f.get("destination_city") or f.get("destination", "")).lower().strip()
        for f in state.flight_options
        if f.get("destination_city") or f.get("destination")
    }
    hotel_dests = {
        (h.get("destination_city") or h.get("city") or "").lower().strip()
        for h in state.hotel_options
        if h.get("destination_city") or h.get("city")
    }

    overlapping = flight_dests & hotel_dests
    if flight_dests and hotel_dests and not overlapping:
        issues.append(
            f"No overlapping destinations: flights go to {sorted(flight_dests)[:3]}, "
            f"hotels are in {sorted(hotel_dests)[:3]}"
        )

    hotels_without_name = sum(
        1 for h in state.hotel_options if not h.get("name")
    )
    if hotels_without_name == len(state.hotel_options) and state.hotel_options:
        issues.append("All hotel records missing names -- unusable")

    return issues


def _build_gate_b_response(state: SharedState, feasibility: dict) -> ExecuteResponse:
    """Build a grounded best-effort response when budget is provably infeasible."""
    _save_session_memory(state)
    dest = state.constraints.get("destinations", ["your destination"])[0] \
        if state.constraints.get("destinations") else "your destination"

    cheapest_flights = sorted(
        state.flight_options, key=lambda f: f.get("price", 9999)
    )[:3]
    cheapest_hotels = sorted(
        state.hotel_options, key=lambda h: h.get("total_price", 9999)
    )[:3]

    dominant = feasibility["dominant_cost"]
    suggestion = (
        "try flexible dates or nearby airports"
        if dominant == "flights"
        else "consider a lower-tier hotel or shorter stay"
    )

    result = {
        "status": "budget_infeasible",
        "message": (
            f"Your budget of ${feasibility['budget']:.0f} is below the minimum "
            f"cost of ~${feasibility['lower_bound']:.0f} for a trip to {dest}."
        ),
        "cost_breakdown": {
            "cheapest_roundtrip_flights": feasibility["cheapest_roundtrip_flight"],
            "cheapest_hotel_total": feasibility["hotel_total"],
            "estimated_daily_expenses": feasibility["daily_expenses"],
            "lower_bound_total": feasibility["lower_bound"],
            "user_budget": feasibility["budget"],
            "gap_percentage": feasibility["gap_pct"],
            "dominant_cost_driver": dominant,
        },
        "cheapest_flights_found": cheapest_flights,
        "cheapest_hotels_found": cheapest_hotels,
        "question": (
            f"The {dominant} are the main cost driver. "
            f"Which would you like to adjust?\n"
            f"  1. Dates (flexible dates can lower flight prices)\n"
            f"  2. Destination (consider a cheaper alternative)\n"
            f"  3. Budget (increase to ~${feasibility['lower_bound']:.0f})\n"
            f"  4. Hotel tier ({suggestion})"
        ),
        "destination_knowledge": [
            c.get("content", "")[:RAG_DISPLAY_CHARS_PLANNER]
            for c in state.destination_chunks[:RAG_MAX_CHUNKS_GATE_B]
        ],
    }

    return ExecuteResponse(
        status="ok",
        error=None,
        response=json.dumps(result, indent=2, default=str),
        steps=[Step(**s) for s in state.steps],
    )


# ═══════════════════════════════════════════════════════════════════════════
#   REJECTION CLASSIFICATION (deterministic)
# ═══════════════════════════════════════════════════════════════════════════

def _classify_rejection(verdict: dict) -> str:
    """Map Verifier rejection issues into a repair category."""
    issues = verdict.get("issues", [])
    categories: dict[str, int] = {}

    for issue in issues:
        lower = issue.lower() if isinstance(issue, str) else ""
        if any(kw in lower for kw in ("budget", "exceed", "cost", "expensive", "price")):
            categories["BUDGET"] = categories.get("BUDGET", 0) + 1
        if any(kw in lower for kw in ("check-in", "check-out", "night", "date", "inconsisten", "arrival", "departure")):
            categories["ALIGNMENT"] = categories.get("ALIGNMENT", 0) + 1
        if any(kw in lower for kw in ("missing", "not provided", "no data", "empty")):
            categories["MISSING_INFO"] = categories.get("MISSING_INFO", 0) + 1
        if any(kw in lower for kw in ("hallucin", "grounding", "coherence", "contradict", "fabricat", "invented")):
            categories["GROUNDING"] = categories.get("GROUNDING", 0) + 1

    if not categories:
        return "GROUNDING"

    return max(categories, key=categories.get)  # type: ignore[arg-type]


def _build_rejection_response(state: SharedState, verdict: dict, repair: str) -> ExecuteResponse:
    """Build a best-effort response when rejected and at cap."""
    question_map = {
        "BUDGET": (
            "The trip plan exceeds your budget. Which would you like to adjust?\n"
            "  1. Dates (flexible dates can lower prices)\n"
            "  2. Destination (consider a cheaper alternative)\n"
            "  3. Budget (increase your budget)\n"
            "  4. Hotel tier (lower-star hotel or shorter stay)"
        ),
        "ALIGNMENT": (
            "There were date/timing inconsistencies in the plan. "
            "Could you confirm your exact travel dates (departure and return)?"
        ),
        "MISSING_INFO": (
            "Some required information was missing. Could you provide:\n"
            + "\n".join(f"  - {iss}" for iss in verdict.get("issues", []))
        ),
        "GROUNDING": (
            "The plan had some unsupported claims. I'll work with verified data only. "
            "Could you let me know if you'd like to adjust any preferences?"
        ),
    }

    _save_session_memory(state)

    # Human-readable summary of why the Verifier rejected the plan.
    issues = verdict.get("issues", [])
    warnings = verdict.get("warnings", [])
    if issues:
        rejection_expl = (
            "The quality Verifier rejected the draft packages because:\n- "
            + "\n- ".join(str(iss) for iss in issues)
        )
    else:
        rejection_expl = (
            "The quality Verifier rejected the draft packages, but did not provide "
            "specific issue messages. This usually means something about the plan "
            "looked unsafe or inconsistent."
        )

    if warnings:
        rejection_expl += (
            "\n\nThe Verifier also raised these warnings (the plan might still be usable, "
            "but you should double-check these points):\n- "
            + "\n- ".join(str(w) for w in warnings)
        )

    rejection_expl += (
        "\n\nBecause the LLM call budget for this request was exhausted, the agent "
        "could not run another full repair-and-verify cycle, so it is returning "
        "the last draft packages as a **best-effort** result together with this explanation."
    )
    response_data = {
        "status": "best_effort",
        "packages": state.draft_plans if state.draft_plans else [],
        "verifier_issues": issues,
        "verifier_warnings": warnings,
        "repair_category": repair,
        "explanation": rejection_expl,
        "question": question_map.get(repair, "Could you provide more details?"),
        "llm_calls_used": state.llm_call_count,
    }

    if state.draft_plans:
        save_trip(
            prompt=state.raw_prompt,
            constraints=state.constraints,
            packages=state.draft_plans,
            llm_calls_used=state.llm_call_count,
            status="best_effort",
            session_id=state.session_id,
        )

    return ExecuteResponse(
        status="ok",
        error=None,
        response=json.dumps(response_data, indent=2, default=str),
        steps=[Step(**s) for s in state.steps],
    )


# ═══════════════════════════════════════════════════════════════════════════
#   RESPONSE BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def _build_final_response(state: SharedState) -> ExecuteResponse:
    """Format the final approved (or best-effort) trip plan."""
    _save_session_memory(state)
    if state.draft_plans:
        formatted = json.dumps(state.draft_plans, indent=2, default=str)
        save_trip(
            prompt=state.raw_prompt,
            constraints=state.constraints,
            packages=state.draft_plans,
            llm_calls_used=state.llm_call_count,
            status="approved",
            session_id=state.session_id,
        )
        save_session(
            session_id=state.session_id,
            prompt=state.raw_prompt,
            state_snapshot={
                "constraints": state.constraints,
                "package_count": len(state.draft_plans),
                "llm_calls_used": state.llm_call_count,
            },
        )
    elif state.final_response:
        formatted = state.final_response
    else:
        formatted = "The agent could not produce a complete trip plan. Please try a more specific request."

    return ExecuteResponse(
        status="ok", error=None, response=formatted,
        steps=[Step(**s) for s in state.steps],
    )


def _planner_call_count(state: SharedState) -> int:
    """Count how many times the Planner LLM was invoked in this run."""
    return sum(1 for s in state.steps if s.get("module") == "Planner")


def _build_best_effort_response(state: SharedState, reason: str) -> ExecuteResponse:
    """Generic best-effort response when we can't complete the full loop."""
    planning_attempts = _planner_call_count(state)
    last_verdict = state.verifier_verdicts[-1] if state.verifier_verdicts else {}
    verifier_issues = last_verdict.get("issues", [])
    verifier_warnings = last_verdict.get("warnings", [])

    # Build a short natural-language reasoning summary so the user can see
    # *why* this is best-effort and how many times planning was attempted.
    reasoning_lines: list[str] = []
    if planning_attempts <= 1:
        reasoning_lines.append(
            "The agent ran one full planning cycle but could not complete the full "
            "Supervisor → Plan → Execute → Synthesize → Verify loop."
        )
    else:
        reasoning_lines.append(
            f"The agent ran the Planner {planning_attempts} times to try to repair or "
            "improve the trip plan, but still could not complete a fully approved loop."
        )

    if state.destination_search_state:
        # Summarise destinations where repeated date variants produced no hotels,
        # so the user can understand why re-planning did not help.
        exhausted_summaries: list[str] = []
        for dest, entry in state.destination_search_state.items():
            empty_ranges = entry.get("hotel_empty_ranges", set())
            tried = entry.get("date_ranges_tried", set())
            if empty_ranges:
                exhausted_summaries.append(
                    f"{dest}: {len(empty_ranges)} date range(s) tried with no hotel availability"
                    + (f" out of {len(tried)} total ranges tested" if tried else "")
                )
        if exhausted_summaries:
            reasoning_lines.append(
                "For some destinations, multiple date ranges were tried but hotels were "
                "still unavailable within your budget:\n- "
                + "\n- ".join(exhausted_summaries)
            )

    if verifier_issues:
        reasoning_lines.append(
            "The Verifier reviewed the last draft packages and flagged issues:\n- "
            + "\n- ".join(str(iss) for iss in verifier_issues)
        )
    elif state.verifier_verdicts:
        reasoning_lines.append(
            "The Verifier reviewed the last draft packages but rejected them without "
            "specific issue text. This usually indicates the plan looked unsafe or inconsistent."
        )

    reasoning_summary = " ".join(reasoning_lines) if reasoning_lines else reason

    if state.draft_plans:
        result = {
            "status": "best_effort",
            "packages": state.draft_plans,
            "note": reason,
            "reasoning_summary": reasoning_summary,
            "verifier_issues": verifier_issues,
            "verifier_warnings": verifier_warnings,
            "planning_attempts": planning_attempts,
            "destination_search_history": state.destination_search_state,
            "llm_calls_used": state.llm_call_count,
        }
        formatted = json.dumps(result, indent=2, default=str)
    else:
        data_summary = {
            "flights_found": len(state.flight_options),
            "hotels_found": len(state.hotel_options),
            "pois_found": len(state.poi_list),
        }
        formatted = json.dumps({
            "status": "best_effort",
            "note": reason,
            "verifier_issues": verifier_issues,
            "verifier_warnings": verifier_warnings,
            "planning_attempts": planning_attempts,
            "destination_search_history": state.destination_search_state,
            "data_collected": data_summary,
            "llm_calls_used": state.llm_call_count,
        }, indent=2, default=str)

    return ExecuteResponse(
        status="ok", error=None, response=formatted,
        steps=[Step(**s) for s in state.steps],
    )


# ═══════════════════════════════════════════════════════════════════════════
#   SESSION MEMORY (multi-turn conversation)
# ═══════════════════════════════════════════════════════════════════════════

def _save_session_memory(state: SharedState) -> None:
    """Save current session state so follow-up requests can resume context.

    Stores: original prompt, constraints, conversation history, plus
    a summary of what was already searched/offered so follow-ups like
    'give me different destinations' or 'cheaper hotel' are understood.
    """
    if len(_session_memory) >= MAX_SESSIONS:
        oldest = next(iter(_session_memory))
        del _session_memory[oldest]

    destinations_searched = list({
        f.get("destination_city", f.get("destination", ""))
        for f in state.flight_options if f.get("destination_city") or f.get("destination")
    })

    packages_summary = []
    for pkg in state.draft_plans:
        packages_summary.append({
            "destination": pkg.get("destination", ""),
            "label": pkg.get("label", ""),
            "total": pkg.get("cost_breakdown", {}).get("total", 0),
        })

    _session_memory[state.session_id] = {
        "original_prompt": state.raw_prompt,
        "constraints": state.constraints.copy() if state.constraints else {},
        "conversation_history": state.conversation_history.copy(),
        "destinations_searched": destinations_searched,
        "packages_offered": packages_summary,
    }


# ── Health check ───────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# ── Serve frontend ─────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend() -> HTMLResponse:
    index_path = FRONTEND_DIR / "index.html"
    if index_path.is_file():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"), status_code=200)
    return HTMLResponse(
        content="<h1>AI Travel Agent</h1><p>Frontend not found.</p>",
        status_code=200,
    )
