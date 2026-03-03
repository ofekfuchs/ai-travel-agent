import json
import time
import traceback

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Dict

from app.config import MAX_SUPERVISOR_ITERATIONS
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
from app.agents.supervisor import run_supervisor
from app.agents.planner import run_planner
from app.agents.executor import run_executor
from app.agents.synthesizer import run_synthesizer
from app.agents.verifier import run_verifier

app = FastAPI(title="AI Travel Agent")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


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


# ── Deterministic budget pre-check (zero LLM calls) ───────────────────────

def _budget_precheck(state: SharedState) -> dict | None:
    """Check if the user's budget can possibly be met with the cheapest
    available flights + hotels. Returns None if OK, or a dict with
    'min_total', 'cheapest_flight', 'cheapest_hotel', 'budget' if impossible.

    This saves LLM calls by catching unrealistic budgets before the
    Synthesizer/Verifier ever run.
    """
    budget = state.constraints.get("budget_total") if state.constraints else None
    if not budget:
        return None

    cheapest_flight = None
    if state.flight_options:
        prices = [f.get("price", 0) for f in state.flight_options if f.get("price")]
        if prices:
            cheapest_flight = min(prices)

    cheapest_hotel = None
    if state.hotel_options:
        totals = [h.get("total_price", 0) for h in state.hotel_options if h.get("total_price")]
        if totals:
            cheapest_hotel = min(totals)

    if cheapest_flight is None or cheapest_hotel is None:
        return None

    min_flight_roundtrip = cheapest_flight * 2
    min_total = min_flight_roundtrip + cheapest_hotel
    budget_num = float(budget)

    if min_total > budget_num * 1.5:
        return {
            "min_total": round(min_total, 2),
            "cheapest_flight_oneway": round(cheapest_flight, 2),
            "cheapest_hotel_total": round(cheapest_hotel, 2),
            "budget": budget_num,
            "gap_pct": round((min_total - budget_num) / budget_num * 100, 1),
        }

    return None


# ── POST /api/execute  (Supervisor loop) ───────────────────────────────────

@app.post("/api/execute", response_model=ExecuteResponse)
async def execute_agent(request: ExecuteRequest) -> ExecuteResponse:
    """Optimized Supervisor loop with budget pre-checks and smart re-planning."""
    try:
        state = SharedState(raw_prompt=request.prompt)

        for iteration in range(MAX_SUPERVISOR_ITERATIONS):
            t0 = time.time()
            print(f"\n{'='*60}")
            print(f"  ITERATION {iteration + 1}/{MAX_SUPERVISOR_ITERATIONS}")
            print(f"{'='*60}")

            # ── Step 1: Supervisor ──
            print(f"  [1/5] Supervisor deciding ...", flush=True)
            decision = run_supervisor(state)
            action = decision.get("next_action", "plan")
            print(f"         -> action={action} ({time.time()-t0:.1f}s)", flush=True)

            if action == "ask_clarification":
                question = decision.get("clarification_question", "Could you provide more details about your trip?")
                return ExecuteResponse(
                    status="ok",
                    error=None,
                    response=question,
                    steps=[Step(**s) for s in state.steps],
                )

            if action == "finalize":
                return _build_final_response(state)

            # ── Step 2: Planner ──
            t1 = time.time()
            print(f"  [2/5] Planner generating tasks ...", flush=True)
            run_planner(state)
            print(f"         -> {len(state.task_list)} tasks ({time.time()-t1:.1f}s)", flush=True)
            for t in state.task_list:
                print(f"           * {t.get('task')}: {t.get('params', {})}", flush=True)

            # ── Step 3: Executor ──
            t2 = time.time()
            print(f"  [3/5] Executor running tasks ...", flush=True)
            run_executor(state)
            print(f"         -> done ({time.time()-t2:.1f}s)", flush=True)
            print(f"           RAG={len(state.destination_chunks)} flights={len(state.flight_options)} "
                  f"hotels={len(state.hotel_options)} weather={len(state.weather_context)} POIs={len(state.poi_list)}", flush=True)

            # ── Budget pre-check (DETERMINISTIC, zero LLM calls) ──
            budget_issue = _budget_precheck(state)
            if budget_issue and iteration == 0:
                print(f"  [!!] BUDGET PRE-CHECK: minimum ${budget_issue['min_total']} > budget ${budget_issue['budget']} "
                      f"(+{budget_issue['gap_pct']}%)", flush=True)
                print(f"       Cheapest flight one-way: ${budget_issue['cheapest_flight_oneway']}", flush=True)
                print(f"       Cheapest hotel total: ${budget_issue['cheapest_hotel_total']}", flush=True)
                print(f"       -> Telling Synthesizer to build best-effort package with budget warning", flush=True)
                state.budget_warning = (
                    f"IMPORTANT: The user's budget is ${budget_issue['budget']}, but the cheapest "
                    f"combination found is ~${budget_issue['min_total']} "
                    f"(flight ${budget_issue['cheapest_flight_oneway']} one-way × 2 + "
                    f"hotel ${budget_issue['cheapest_hotel_total']}). "
                    f"Build the cheapest possible package and clearly explain the budget gap. "
                    f"Do NOT invent cheaper options. Show the real cheapest options."
                )

            # ── Step 4: Synthesizer ──
            t3 = time.time()
            print(f"  [4/5] Synthesizer building packages ...", flush=True)
            run_synthesizer(state)
            print(f"         -> {len(state.draft_plans)} packages ({time.time()-t3:.1f}s)", flush=True)

            # ── Step 5: Verifier ──
            t4 = time.time()
            print(f"  [5/5] Verifier auditing ...", flush=True)
            verdict = run_verifier(state)
            vdecision = verdict.get("decision", "REJECT")
            print(f"         -> {vdecision} ({time.time()-t4:.1f}s)", flush=True)
            if verdict.get("issues"):
                for iss in verdict["issues"]:
                    print(f"           ! {iss}", flush=True)

            if vdecision == "APPROVE":
                print(f"\n  APPROVED in {time.time()-t0:.1f}s total", flush=True)
                return _build_final_response(state)

            # ── Smart rejection handling ──
            issues = verdict.get("issues", [])
            only_budget = all("budget" in iss.lower() or "exceed" in iss.lower() for iss in issues if iss)

            if only_budget and budget_issue:
                print(f"\n  BUDGET-ONLY REJECTION on impossible budget -- returning best-effort.", flush=True)
                return _build_final_response(state)

            if iteration == MAX_SUPERVISOR_ITERATIONS - 1:
                print(f"\n  Max iterations reached, returning best-effort.", flush=True)
                return _build_final_response(state)

            print(f"\n  REJECTED -- will re-plan (passing issues to Planner) ...", flush=True)

        return _build_final_response(state)

    except Exception as exc:
        print(f"\n  ERROR: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return ExecuteResponse(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            response=None,
            steps=[],
        )


def _build_final_response(state: SharedState) -> ExecuteResponse:
    """Format the final approved (or best-effort) trip plan as the API response."""
    if state.draft_plans:
        formatted = json.dumps(state.draft_plans, indent=2, default=str)
    elif state.final_response:
        formatted = state.final_response
    else:
        formatted = "The agent could not produce a complete trip plan. Please try a more specific request."

    return ExecuteResponse(
        status="ok",
        error=None,
        response=formatted,
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
    return HTMLResponse(content="<h1>AI Travel Agent</h1><p>Frontend not found.</p>", status_code=200)
