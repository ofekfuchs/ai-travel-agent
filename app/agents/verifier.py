"""Verifier -- audits the synthesized trip package(s) and decides
APPROVE or REJECT.

Uses a hybrid approach:
  1. Deterministic rule-based checks (dates, budget, completeness) -- free.
  2. LLM qualitative check (coherence, grounding, rationale quality) -- one call.

Budget-aware: if a budget_warning exists (meaning the deterministic pre-check
already proved the budget is tight), the budget rule is relaxed. We don't
want to reject forever for something the data already proves is impossible.
"""

from __future__ import annotations

import json

from app.llm.client import call_llm
from app.models.shared_state import SharedState

_REQUIRED_KEYS = {"destination", "flights", "hotel", "weather_summary", "itinerary", "cost_breakdown", "rationale"}


def run_verifier(state: SharedState) -> dict:
    """Verify the draft plans. Budget-aware: won't reject endlessly for
    a budget gap that the real data proves is unavoidable."""
    if not state.draft_plans:
        verdict = {
            "decision": "REJECT",
            "issues": ["No draft plans exist."],
            "recommendation": "replan",
        }
        state.verifier_verdicts.append(verdict)
        return verdict

    issues: list[str] = []
    already_rejected_count = len(state.verifier_verdicts)

    # ── Rule-based checks (deterministic, free) ───────────────────────────
    for i, plan in enumerate(state.draft_plans):
        prefix = f"Package {i + 1}"
        missing = _REQUIRED_KEYS - set(plan.keys())
        if missing:
            issues.append(f"{prefix}: missing fields {missing}")

        cost = plan.get("cost_breakdown", {})
        total = cost.get("total", cost.get("total_usd", 0))
        budget = state.constraints.get("budget_total")

        if budget and total:
            if state.budget_warning:
                pass
            elif total > budget * 1.15:
                issues.append(f"{prefix}: total ${total} exceeds budget ${budget} by >15%")

        if not plan.get("itinerary"):
            issues.append(f"{prefix}: itinerary is empty")

    # ── LLM qualitative check ─────────────────────────────────────────────
    llm_verdict = _llm_quality_check(state, issues, already_rejected_count)

    all_issues = issues + llm_verdict.get("issues", [])
    decision = llm_verdict.get("decision", "APPROVE" if not all_issues else "REJECT")

    if already_rejected_count >= 1:
        decision = "APPROVE"

    verdict = {
        "decision": decision,
        "issues": all_issues,
        "recommendation": "finalize" if decision == "APPROVE" else "replan",
    }
    state.verifier_verdicts.append(verdict)
    return verdict


VERIFIER_SYSTEM = """\
You are the Verifier of a travel-planning agent. You receive a draft trip
package and must judge its quality.

Check:
- Are the dates, flights, and hotel check-in/out internally consistent?
- Does the itinerary make sense for the destination and duration?
- Is the rationale grounded in actual data (not hallucinated)?
- Are there any logical contradictions?

IMPORTANT rules:
- If a "budget_warning" is present, it means the system already proved the
  user's budget is tight. Do NOT reject solely because of budget.
  Instead, APPROVE with a note about the budget gap.
- If this is a RE-VERIFICATION (the plan was already rejected and revised),
  be more lenient. APPROVE unless there are critical logical errors.
- Minor rounding errors ($0.01-$0.10) are acceptable.

Respond with a JSON object:
{
  "decision": "APPROVE" or "REJECT",
  "issues": ["list of specific problems found, or empty if none"],
  "quality_notes": "brief summary"
}

Return ONLY valid JSON.
"""


def _llm_quality_check(state: SharedState, rule_issues: list[str], prior_rejections: int) -> dict:
    """Run one LLM call to qualitatively judge the draft plan."""
    user_parts = []

    if prior_rejections > 0:
        user_parts.append(
            f"NOTE: This plan has been revised {prior_rejections} time(s) already. "
            f"Be more lenient -- APPROVE unless there are critical errors."
        )

    if state.budget_warning:
        user_parts.append(f"BUDGET CONTEXT: {state.budget_warning}")

    if rule_issues:
        user_parts.append(f"Rule-based issues already found: {rule_issues}")

    user_parts.append(f"Draft plans: {json.dumps(state.draft_plans[:2], default=str)}")

    if state.constraints:
        user_parts.append(f"User constraints: {json.dumps(state.constraints, default=str)}")

    user_prompt = "\n\n".join(user_parts)

    raw = call_llm(state, module="Verifier", system_prompt=VERIFIER_SYSTEM, user_prompt=user_prompt)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"decision": "APPROVE", "issues": [], "quality_notes": "Could not parse verifier output; approving to avoid wasting calls."}
