"""Supervisor -- the autonomous decision-making brain of the agent.

Called MULTIPLE TIMES during a single run at each decision point:
  1. Initial: decides whether to clarify, plan, or finalize.
  2. After partial execution: observes intermediate results, decides
     whether to continue executing, pivot destinations, or synthesize.
  3. After verification: decides whether to finalize or replan.

This multi-call pattern is what makes the system an AGENT rather than
a static workflow. The Supervisor reasons about observations at every step.
"""

from __future__ import annotations

import json

from app.llm.client import call_llm
from app.models.shared_state import SharedState

SYSTEM_PROMPT = """\
You are the Supervisor — the autonomous decision-making brain of a travel
planning agent. You are called at EVERY decision point during the trip
planning process. Each time you observe the current state and decide the
next action.

SCOPE GUARD: If the user's message is NOT about planning a trip (e.g.,
writing code, recipes, general knowledge, math, or anything unrelated to
travel), choose "ask_clarification" and politely explain:
"I'm an AI Travel Planning Agent — I can only help with trip planning.
Could you describe a trip you'd like me to plan?"
CRITICAL: In follow-up messages, apply the scope guard to the LATEST
USER MESSAGE only. Even if prior context is about travel, if the new
message is off-topic, reject it immediately — do NOT continue planning.

Respond with a JSON object (no markdown, no extra text):
{
  "next_action": "<one of the actions below>",
  "reason": "<one sentence explaining your reasoning based on what you observed>",
  "clarification_question": "<only if next_action is ask_clarification, else null>",
  "pivot_instructions": "<only if next_action is pivot, else null>"
}

Available actions:

  "ask_clarification" — Critical info is missing or the request is out of
      scope. Use when:
      (a) Origin/departure city is absent and cannot be inferred, OR
      (b) The request is not about travel planning (scope guard).
      Do NOT ask for clarification just because dates are vague — the
      Planner can pick reasonable dates from "June", "summer", "next month".

  "plan" — Enough info exists to create a task plan. Proceed to Planner.
      Requires at minimum: an origin (city or country) AND some travel
      intent (destination hint, season, or interests).

  "continue" — Partial results look good. Continue executing remaining
      destination groups in the task plan.

  "pivot" — Partial results are problematic (too expensive, no availability,
      poor options). Provide pivot_instructions telling the Planner what to
      change (e.g. "search cheaper destinations like Lisbon and Bucharest"
      or "try flexible dates ±3 days").

  "synthesize" — Enough data has been collected to build trip packages.
      Skip remaining tasks and go straight to the Trip Synthesizer.

  "finalize" — An approved trip plan exists. Return it to the user.

  "replan" — The Verifier rejected the plan. Trigger delta replanning.

REASONING GUIDELINES:

- After partial execution: look at flight prices vs budget. If the cheapest
  flights for a destination exceed 60% of the total budget, that destination
  is likely too expensive — consider pivoting.

- If at least 2 destinations have good flight + hotel data, "synthesize"
  is usually the right call — the Synthesizer can pick the best options.
  More destinations = better packages for the user.

- If only 1 destination was searched and remaining destinations exist in the
  plan, "continue" to search more for comparison.

- BUDGET AWARENESS: You have a limited LLM call budget. Each time YOU run
  is 1 call. The Planner, Synthesizer, and Verifier each cost 1 call.
  Typical successful flow uses 5-6 calls total.
  * If 4+ calls are already used, prefer "synthesize" over "plan" or "continue".
  * NEVER choose "plan" if flights and hotels already exist — choose "synthesize".
  * Choosing "plan" when the Planner has nothing new to search wastes 2 calls.

- SINGLE DESTINATION: If only one destination was requested (e.g., "trip to
  London"), and flights + hotels for that destination are already collected,
  immediately choose "synthesize". Do NOT plan again.

- Be decisive. Don't ask for clarification if you can reasonably infer
  the missing info. "June" = summer dates, "cheap" = budget focus, etc.
  But DO ask if origin is truly unknown — flights can't be searched without it.
"""


def run_supervisor(state: SharedState) -> dict:
    """Call the LLM to decide the next action based on the full current state."""
    user_context_parts = []

    is_followup = state.conversation_history and len(state.conversation_history) > 1
    latest = state.latest_user_message or state.raw_prompt

    if is_followup and latest != state.raw_prompt:
        user_context_parts.append(
            f"LATEST USER MESSAGE (evaluate this FIRST for scope guard): {latest}"
        )
        user_context_parts.append(f"Full merged context: {state.raw_prompt}")
        user_context_parts.append(
            "CONVERSATION CONTEXT: This is a follow-up message. The user previously "
            "provided information that was merged into the context above. "
            "IMPORTANT: Apply the scope guard to the LATEST USER MESSAGE. "
            "If the latest message is NOT about travel planning, immediately "
            "choose ask_clarification regardless of prior travel context."
        )
    else:
        user_context_parts.append(f"User prompt: {state.raw_prompt}")

    if state.constraints:
        user_context_parts.append(
            f"Extracted constraints: {json.dumps(state.constraints, default=str)}"
        )
        missing = []
        if not state.constraints.get("origin"):
            missing.append("origin")
        has_dates = (
            state.constraints.get("start_date")
            or state.constraints.get("end_date")
            or state.constraints.get("season")
        )
        if not has_dates:
            missing.append("date window / season")
        if missing:
            user_context_parts.append(f"MISSING critical fields: {missing}")
    else:
        user_context_parts.append("No constraints extracted yet (first call).")

    # Data collected so far (the Supervisor sees this to reason about progress)
    data_summary = {
        "rag_chunks": len(state.destination_chunks),
        "flights": len(state.flight_options),
        "hotels": len(state.hotel_options),
        "weather": len(state.weather_context),
        "pois": len(state.poi_list),
    }
    user_context_parts.append(f"Data collected so far: {json.dumps(data_summary)}")

    # Per-destination observations (helps Supervisor reason about which destinations are viable)
    if state.flight_options or state.hotel_options:
        budget = state.constraints.get("budget_total") if state.constraints else None
        dest_obs = _build_destination_observations(state, budget)
        if dest_obs:
            user_context_parts.append(f"Per-destination observations:\n{dest_obs}")
        if budget:
            user_context_parts.append(f"User budget: ${budget}")

    # Remaining tasks
    if state.task_list:
        remaining_groups = list({t.get("destination_group", "?") for t in state.task_list
                                if t.get("destination_group")})
        user_context_parts.append(f"Remaining destination groups in plan: {remaining_groups}")

    if state.verifier_verdicts:
        last = state.verifier_verdicts[-1]
        user_context_parts.append(f"Last verifier verdict: {json.dumps(last, default=str)}")

    if state.draft_plans:
        user_context_parts.append(f"Draft plans exist: {len(state.draft_plans)} package(s).")

    user_context_parts.append(f"LLM calls used: {state.llm_call_count}/{state.llm_call_cap}")

    user_prompt = "\n".join(user_context_parts)

    raw = call_llm(state, module="Supervisor", system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {
            "next_action": "plan" if not state.flight_options else "synthesize",
            "reason": "Could not parse LLM output; defaulting based on state.",
            "clarification_question": None,
            "pivot_instructions": None,
        }

    return decision


def _build_destination_observations(state: SharedState, budget) -> str:
    """Build a compact per-destination summary for the Supervisor.

    Groups flights and hotels by destination so the Supervisor can compare
    destinations and reason about viability (e.g., pivot away from expensive ones).
    """
    dest_data: dict[str, dict] = {}

    for f in state.flight_options:
        dest = f.get("destination_city", f.get("destination", "?"))
        entry = dest_data.setdefault(dest, {"flights": [], "hotels": [], "direct": False})
        price = f.get("price", 0)
        if price:
            entry["flights"].append(price)
        if f.get("stops", 99) == 0:
            entry["direct"] = True

    for h in state.hotel_options:
        dest = h.get("destination_city", "?")
        entry = dest_data.setdefault(dest, {"flights": [], "hotels": [], "direct": False})
        tp = h.get("total_price", 0)
        if tp:
            entry["hotels"].append(tp)

    if not dest_data:
        return ""

    lines = []
    for dest, info in dest_data.items():
        parts = [f"  {dest}:"]
        fprices = info["flights"]
        hprices = info["hotels"]
        if fprices:
            parts.append(f"flights=${min(fprices):.0f}-${max(fprices):.0f} ({len(fprices)} options)")
            if info["direct"]:
                parts.append("(direct available)")
        else:
            parts.append("no flights")
        if hprices:
            parts.append(f"hotels=${min(hprices):.0f}-${max(hprices):.0f} ({len(hprices)} options)")
        else:
            parts.append("no hotels")
        if budget and fprices and hprices:
            try:
                lower = min(fprices) + min(hprices)
                pct = lower / float(budget) * 100
                parts.append(f"min total=${lower:.0f} ({pct:.0f}% of budget)")
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        lines.append(" ".join(parts))

    return "\n".join(lines)
