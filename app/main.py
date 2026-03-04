"""Main FastAPI application and Supervisor orchestration loop.

Architecture: Supervisor → Planner → Executor → Trip Synthesizer → Verifier

Key principles:
- Hard cap of 5 LLM calls per /api/execute invocation.
- Supervisor is the SOLE decision maker (ask_clarification / plan / finalize).
- Gate B (after Executor): budget infeasibility → return best-effort + question.
  This is an orchestrator optimization, not a routing decision.
- Strict Verifier: never auto-approve. Cap handling in THIS loop, not in Verifier.
- Delta replanning: if rejected and under cap, classify repair category.
"""

import json
import time
import traceback

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Dict

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
from app.agents.planner import run_planner
from app.agents.executor import run_executor
from app.agents.synthesizer import run_synthesizer
from app.agents.verifier import run_verifier

app = FastAPI(title="AI Travel Agent")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

DAILY_EXPENSES_ESTIMATE = 50
BUDGET_TOLERANCE = 1.05

MAX_LOOP_ITERATIONS = 2


# ── GET /api/team_info ─────────────────────────────────────────────────────

@app.get("/api/team_info", response_model=TeamInfoResponse)
async def get_team_info() -> TeamInfoResponse:
    return TeamInfoResponse(
        group_batch_order_number="3_11",
        team_name="Ofek & Omri",
        students=[
            TeamInfoStudent(name="Ofek Fuchs", email="ofek.fuchs@campus.technion.ac.il"),
            TeamInfoStudent(name="Omri Lazover", email="omri.lazover@campus.technion.ac.il"),
        ],
    )


# ── GET /api/agent_info ────────────────────────────────────────────────────

@app.get("/api/agent_info", response_model=AgentInfoResponse)
async def get_agent_info() -> AgentInfoResponse:
    dummy_step = Step(
        module="Supervisor",
        prompt={"system": "You are the Supervisor.", "user": "Plan me a trip."},
        response={"content": "Routing to Planner."},
    )
    example = AgentInfoPromptExample(
        prompt="A week in May, somewhere in Europe with good weather, best value for money.",
        full_response="(Full response will be populated after end-to-end implementation.)",
        steps=[dummy_step],
    )
    return AgentInfoResponse(
        description=(
            "Full-Package AI Travel Agent. Given a free-form travel request, "
            "the agent autonomously recommends destinations, finds flights and "
            "hotels, checks weather, builds a day-by-day itinerary, and returns "
            "a complete priced trip package with rationale."
        ),
        purpose=(
            "Solve the problem of planning trips from vague, flexible intent. "
            "Users no longer need exact dates or destinations upfront."
        ),
        prompt_template=AgentInfoPromptTemplate(
            template=(
                "Describe your ideal trip in free-form text. For example: "
                "desired region, rough dates or season, budget range, pace "
                "(relaxed / active), interests (beaches, culture, nightlife…), "
                "and number of travellers."
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
    """Main orchestration loop with LLM call cap and Gate B optimization."""
    try:
        state = SharedState(raw_prompt=request.prompt)

        for iteration in range(MAX_LOOP_ITERATIONS):
            t0 = time.time()
            print(f"\n{'='*60}", flush=True)
            print(f"  ITERATION {iteration + 1}/{MAX_LOOP_ITERATIONS}  "
                  f"(LLM calls used: {state.llm_call_count}/{state.llm_call_cap})", flush=True)
            print(f"{'='*60}", flush=True)

            # ── Step 1: Supervisor ──────────────────────────────────────
            if not state.can_call_llm():
                print("  LLM cap reached before Supervisor -- returning best-effort", flush=True)
                return _build_best_effort_response(state, "LLM call budget exhausted.")
            print(f"  [1/5] Supervisor deciding ...", flush=True)
            decision = run_supervisor(state)
            action = decision.get("next_action", "plan")
            print(f"         -> action={action} (calls: {state.llm_call_count})", flush=True)

            if action == "ask_clarification":
                question = decision.get(
                    "clarification_question",
                    "Could you provide more details about your trip?"
                )
                return ExecuteResponse(
                    status="ok", error=None, response=question,
                    steps=[Step(**s) for s in state.steps],
                )

            if action == "finalize":
                return _build_final_response(state)

            # ── Step 2: Planner ─────────────────────────────────────────
            repair_cat = None
            if iteration > 0 and state.verifier_verdicts:
                repair_cat = _classify_rejection(state.verifier_verdicts[-1])
                print(f"         Repair category: {repair_cat}", flush=True)

            if not state.can_call_llm():
                print("  LLM cap reached before Planner -- returning best-effort", flush=True)
                return _build_best_effort_response(state, "LLM call budget exhausted.")
            t1 = time.time()
            print(f"  [2/5] Planner generating tasks ...", flush=True)
            run_planner(state, repair_category=repair_cat)
            print(f"         -> {len(state.task_list)} tasks ({time.time()-t1:.1f}s, calls: {state.llm_call_count})", flush=True)
            for t in state.task_list:
                print(f"           * {t.get('task')}: {t.get('params', {})}", flush=True)

            # ── Step 3: Executor ────────────────────────────────────────
            t2 = time.time()
            print(f"  [3/5] Executor running tasks ...", flush=True)
            run_executor(state)
            print(f"         -> done ({time.time()-t2:.1f}s, calls: {state.llm_call_count})", flush=True)
            print(f"           flights={len(state.flight_options)} "
                  f"hotels={len(state.hotel_options)} weather={len(state.weather_context)} "
                  f"POIs={len(state.poi_list)} RAG={len(state.destination_chunks)}", flush=True)

            # ── Data guard: don't synthesize without pricing data ──────
            if not state.flight_options and not state.hotel_options:
                print(f"  NO PRICING DATA: flights=0 hotels=0 -- cannot synthesize", flush=True)
                return _build_no_data_response(state)

            # ── GATE B: Feasibility Check (orchestrator optimization) ──
            feasibility = _feasibility_check(state)
            if feasibility:
                print(f"  GATE B TRIGGERED: lower_bound=${feasibility['lower_bound']:.0f} "
                      f"> budget=${feasibility['budget']:.0f} "
                      f"(gap +{feasibility['gap_pct']:.0f}%)", flush=True)
                print(f"  Returning best-effort grounded response + question", flush=True)
                return _build_gate_b_response(state, feasibility)

            # ── Step 4: Trip Synthesizer ────────────────────────────────
            if not state.can_call_llm():
                print("  LLM cap reached before Synthesizer -- returning best-effort", flush=True)
                return _build_best_effort_response(state, "LLM call budget exhausted.")
            t3 = time.time()
            tight = _is_budget_tight(state)
            pkg_mode = "1 (tight budget)" if tight else "2-3 (tiered)"
            print(f"  [4/5] Synthesizer building {pkg_mode} package(s) ...", flush=True)
            run_synthesizer(state, tight_budget=tight)
            print(f"         -> {len(state.draft_plans)} packages ({time.time()-t3:.1f}s, calls: {state.llm_call_count})", flush=True)

            # ── Step 5: Verifier ────────────────────────────────────────
            if not state.can_call_llm():
                print("  LLM cap reached before Verifier -- returning synthesized result as-is", flush=True)
                return _build_final_response(state)
            t4 = time.time()
            print(f"  [5/5] Verifier auditing ...", flush=True)
            verdict = run_verifier(state)
            vdecision = verdict.get("decision", "REJECT")
            print(f"         -> {vdecision} ({time.time()-t4:.1f}s, calls: {state.llm_call_count})", flush=True)
            if verdict.get("issues"):
                for iss in verdict["issues"]:
                    print(f"           ! {iss}", flush=True)

            if vdecision == "APPROVE":
                print(f"\n  APPROVED in {time.time()-t0:.1f}s total", flush=True)
                return _build_final_response(state)

            # ── Rejection handling ──────────────────────────────────────
            if not state.can_call_llm():
                print(f"  REJECTED but LLM cap reached -- returning best-effort + question", flush=True)
                repair = _classify_rejection(verdict)
                return _build_rejection_response(state, verdict, repair)

            if iteration == MAX_LOOP_ITERATIONS - 1:
                print(f"  Max iterations reached -- returning best-effort + question", flush=True)
                repair = _classify_rejection(verdict)
                return _build_rejection_response(state, verdict, repair)

            print(f"\n  REJECTED -- will delta-replan ...", flush=True)

        return _build_best_effort_response(state, "Loop exhausted.")

    except LLMCapReached as exc:
        print(f"\n  LLM CAP REACHED (safety net): {exc}", flush=True)
        return _build_best_effort_response(state, str(exc))

    except Exception as exc:
        print(f"\n  ERROR: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return ExecuteResponse(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            response=None,
            steps=[Step(**s) for s in state.steps],
        )


# ═══════════════════════════════════════════════════════════════════════════
#   No-data response
# ═══════════════════════════════════════════════════════════════════════════

def _build_no_data_response(state: SharedState) -> ExecuteResponse:
    """Return when pricing tools returned no results."""
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

    flight_cost = (cheapest_flight or 0) * 2
    hotel_cost = cheapest_hotel or 0

    duration = state.constraints.get("duration_days") or 4
    try:
        duration = int(duration)
    except (ValueError, TypeError):
        duration = 4

    daily_expenses = DAILY_EXPENSES_ESTIMATE * duration
    lower_bound = flight_cost + hotel_cost + daily_expenses

    if lower_bound > budget_num * BUDGET_TOLERANCE:
        return {
            "lower_bound": lower_bound,
            "flight_rt": flight_cost,
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

    cheapest_flight = _cheapest_price(state.flight_options, "price")
    cheapest_hotel = _cheapest_price(state.hotel_options, "total_price")
    flight_cost = (cheapest_flight or 0) * 2
    hotel_cost = cheapest_hotel or 0
    duration = state.constraints.get("duration_days") or 4
    try:
        duration = int(duration)
    except (ValueError, TypeError):
        duration = 4
    lower_bound = flight_cost + hotel_cost + (DAILY_EXPENSES_ESTIMATE * duration)

    return lower_bound > budget_num * 0.85


def _build_gate_b_response(state: SharedState, feasibility: dict) -> ExecuteResponse:
    """Build a grounded best-effort response when budget is provably infeasible."""
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
            "cheapest_roundtrip_flights": feasibility["flight_rt"],
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
            c.get("content", "")[:200] for c in state.destination_chunks[:3]
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

    response_data = {
        "status": "best_effort",
        "packages": state.draft_plans if state.draft_plans else [],
        "verifier_issues": verdict.get("issues", []),
        "repair_category": repair,
        "question": question_map.get(repair, "Could you provide more details?"),
        "llm_calls_used": state.llm_call_count,
    }

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
    if state.draft_plans:
        formatted = json.dumps(state.draft_plans, indent=2, default=str)
    elif state.final_response:
        formatted = state.final_response
    else:
        formatted = "The agent could not produce a complete trip plan. Please try a more specific request."

    return ExecuteResponse(
        status="ok", error=None, response=formatted,
        steps=[Step(**s) for s in state.steps],
    )


def _build_best_effort_response(state: SharedState, reason: str) -> ExecuteResponse:
    """Generic best-effort response when we can't complete the full loop."""
    if state.draft_plans:
        result = {
            "status": "best_effort",
            "packages": state.draft_plans,
            "note": reason,
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
            "data_collected": data_summary,
            "llm_calls_used": state.llm_call_count,
        }, indent=2, default=str)

    return ExecuteResponse(
        status="ok", error=None, response=formatted,
        steps=[Step(**s) for s in state.steps],
    )


# ── Health check ───────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# ── Serve frontend ─────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend() -> HTMLResponse:
    index_path = FRONTEND_DIR / "index.html"
    if index_path.is_file():
        return HTMLResponse(content=index_path.read_text(), status_code=200)
    return HTMLResponse(
        content="<h1>AI Travel Agent</h1><p>Frontend not found.</p>",
        status_code=200,
    )
