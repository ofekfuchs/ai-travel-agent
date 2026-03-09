"""Verifier -- strict auditor of synthesized trip packages.

Uses a hybrid approach:
  1. Deterministic rule-based checks (dates, budget, completeness) -- free.
  2. LLM qualitative check (coherence, grounding, rationale quality) -- one call.

Policy: the Verifier NEVER auto-approves.  If JSON parsing fails, it defaults
to REJECT (fail-closed).  The Supervisor / main loop decides how to handle
rejections -- the Verifier's only job is honest auditing.
"""

from __future__ import annotations

import json

from app.llm.client import call_llm
from app.models.shared_state import SharedState

_REQUIRED_KEYS = {
    "destination", "flights", "hotel", "weather_summary",
    "itinerary", "cost_breakdown", "rationale",
}


def run_verifier(state: SharedState) -> dict:
    """Strictly verify the draft plans. Returns a verdict dict."""
    if not state.draft_plans:
        verdict = {
            "decision": "REJECT",
            "issues": ["No draft plans exist."],
            "recommendation": "replan",
        }
        state.verifier_verdicts.append(verdict)
        return verdict

    issues: list[str] = []

    # ── Deterministic rule-based checks (free) ─────────────────────────────
    for i, plan in enumerate(state.draft_plans):
        prefix = f"Package {i + 1}"
        missing = _REQUIRED_KEYS - set(plan.keys())
        if missing:
            issues.append(f"{prefix}: missing fields {missing}")

        cost = plan.get("cost_breakdown", {})
        total = cost.get("total", cost.get("total_usd", 0))
        budget = state.constraints.get("budget_total")

        if budget and total:
            try:
                budget_num = float(budget)
                total_num = float(total)
                if total_num > budget_num * 1.15:
                    issues.append(
                        f"{prefix}: total ${total_num:.0f} exceeds budget ${budget_num:.0f} by "
                        f">{((total_num - budget_num) / budget_num * 100):.0f}%"
                    )
            except (ValueError, TypeError):
                pass

        if not plan.get("itinerary"):
            issues.append(f"{prefix}: itinerary is empty")

        flights = plan.get("flights", {})
        if isinstance(flights, dict):
            if not flights.get("outbound"):
                issues.append(f"{prefix}: missing outbound flight details")
        elif not flights:
            issues.append(f"{prefix}: flights data is empty")

    # ── LLM qualitative check ──────────────────────────────────────────────
    llm_verdict = _llm_quality_check(state, issues)

    llm_issues = llm_verdict.get("issues", [])
    llm_warnings = llm_verdict.get("warnings", [])
    all_issues = issues + llm_issues
    decision = llm_verdict.get("decision", "REJECT" if all_issues else "APPROVE")

    verdict = {
        "decision": decision,
        "issues": all_issues,
        "warnings": llm_warnings,
        "recommendation": "finalize" if decision == "APPROVE" else "replan",
    }
    state.verifier_verdicts.append(verdict)
    return verdict


_VERIFIER_SYSTEM = """\
You are a pragmatic quality auditor of a travel-planning agent. You receive
draft trip packages and must judge whether they are good enough to show the user.

Check for CRITICAL issues (these REQUIRE rejection):
- Fabricated/invented prices not present in the source data
- Missing core fields (no flights, no hotel, no destination)
- Cost breakdown total is wildly wrong (off by >30%)
- Itinerary for wrong destination or completely incoherent

Check for MINOR issues (note them but still APPROVE):
- Small rounding differences (< $5)
- Different airports in the same metro area (e.g. EWR vs JFK for NYC)
- Missing daily expense estimates (acceptable if noted in assumptions)
- Booking links that are search URLs rather than direct deeplinks
- Minor timing nuances (e.g. late-night arrival phrasing)
- Unsubstantiated superlatives in rationale (e.g. "best value")

Decision rules:
- If there are ANY critical issues → "REJECT"
- If there are ONLY minor issues → "APPROVE" (list them as warnings)
- If no issues → "APPROVE"

Respond with a JSON object:
{
  "decision": "APPROVE" or "REJECT",
  "issues": ["list of critical problems, or empty"],
  "warnings": ["list of minor notes, or empty"],
  "quality_notes": "brief summary"
}

Return ONLY valid JSON.
"""


def _llm_quality_check(state: SharedState, rule_issues: list[str]) -> dict:
    """Run one LLM call to qualitatively judge the draft plan."""
    user_parts = []

    if rule_issues:
        user_parts.append(f"Rule-based issues already found: {rule_issues}")

    user_parts.append(f"Draft plans: {json.dumps(state.draft_plans[:2], default=str)}")

    if state.constraints:
        user_parts.append(f"User constraints: {json.dumps(state.constraints, default=str)}")

    user_prompt = "\n\n".join(user_parts)

    raw = call_llm(state, module="Verifier", system_prompt=_VERIFIER_SYSTEM, user_prompt=user_prompt)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fail-closed: if we can't parse the LLM output, REJECT
        return {
            "decision": "REJECT",
            "issues": ["Verifier LLM output was not valid JSON -- fail-closed."],
            "quality_notes": "Parse failure.",
        }
