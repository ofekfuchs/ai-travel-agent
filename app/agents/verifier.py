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
from datetime import datetime, timedelta

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
    det_warnings: list[str] = []

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
            outbound = flights.get("outbound", {})
            if isinstance(outbound, dict):
                airline = outbound.get("airline", "").lower()
                if any(fake in airline for fake in ("drive", "self-drive", "bus", "train", "ferry", "car")):
                    issues.append(
                        f"{prefix}: fabricated ground transport '{outbound.get('airline')}' "
                        f"instead of real flight — destination has no commercial flights"
                    )
        elif not flights:
            issues.append(f"{prefix}: flights data is empty")

        # ── Flight date sanity checks ────────────────────────────────────────
        _check_flight_dates(plan, state, prefix, issues)

        # ── Hotel data completeness check ────────────────────────────────────
        _check_hotel_data(plan, prefix, issues, det_warnings)

        # ── Itinerary-date alignment check ───────────────────────────────────
        _check_itinerary_date_alignment(plan, prefix, issues)

        # ── Price grounding check: verify package prices exist in tool data ──
        _cross_check_prices(plan, state, prefix, issues)

    # ── LLM qualitative check ──────────────────────────────────────────────
    llm_verdict = _llm_quality_check(state, issues)

    llm_issues = llm_verdict.get("issues", [])
    llm_warnings = llm_verdict.get("warnings", [])
    all_issues = issues + llm_issues
    all_warnings = det_warnings + llm_warnings
    decision = llm_verdict.get("decision", "REJECT" if all_issues else "APPROVE")

    verdict = {
        "decision": decision,
        "issues": all_issues,
        "warnings": all_warnings,
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
        constraints_for_verifier = state.constraints.copy()
        excluded = constraints_for_verifier.pop("excluded_destinations", None)
        user_parts.append(f"User constraints: {json.dumps(constraints_for_verifier, default=str)}")
        if excluded:
            user_parts.append(
                f"NOTE: The user explicitly asked for DIFFERENT/ALTERNATIVE destinations. "
                f"The previous destinations were: {excluded}. The new packages SHOULD "
                f"use different cities — this is NOT a destination mismatch error."
            )
    else:
        user_parts.append("User constraints: none")

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


def _parse_dt(val: str) -> datetime | None:
    """Best-effort parse of ISO-ish datetime strings from LLM output."""
    if not val or not isinstance(val, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(val.strip(), fmt)
        except ValueError:
            continue
    return None


def _check_flight_dates(plan: dict, state: SharedState, prefix: str, issues: list[str]) -> None:
    """Sanity-check flight datetimes: detect impossible sequences."""
    flights = plan.get("flights", {})
    if not isinstance(flights, dict):
        return

    outbound = flights.get("outbound", {})
    ret = flights.get("return", flights.get("return_flight", {}))

    if isinstance(outbound, dict) and outbound.get("departure") and outbound.get("arrival"):
        dep = _parse_dt(outbound["departure"])
        arr = _parse_dt(outbound["arrival"])
        if dep and arr:
            if arr < dep:
                issues.append(f"{prefix}: outbound arrival ({outbound['arrival']}) is before departure ({outbound['departure']})")
            elif (arr - dep) > timedelta(hours=30):
                issues.append(f"{prefix}: outbound flight duration exceeds 30h — likely a date error")

    if isinstance(ret, dict) and ret.get("departure") and ret.get("arrival"):
        rdep = _parse_dt(ret["departure"])
        rarr = _parse_dt(ret["arrival"])
        if rdep and rarr:
            if rarr < rdep:
                issues.append(f"{prefix}: return arrival is before return departure")

        # Return should be after outbound arrival
        if isinstance(outbound, dict) and outbound.get("arrival"):
            out_arr = _parse_dt(outbound["arrival"])
            if out_arr and rdep and rdep < out_arr:
                issues.append(f"{prefix}: return departure ({ret['departure']}) is before outbound arrival ({outbound['arrival']})")

    # Verify flight dates fall within the package date_window
    date_window = plan.get("date_window", "")
    if isinstance(date_window, str) and " to " in date_window:
        parts = date_window.split(" to ")
        win_start = _parse_dt(parts[0].strip())
        win_end = _parse_dt(parts[1].strip())
        if win_start and win_end:
            if isinstance(outbound, dict) and outbound.get("departure"):
                dep = _parse_dt(outbound["departure"])
                if dep and (dep.date() < (win_start - timedelta(days=1)).date()
                            or dep.date() > (win_end + timedelta(days=1)).date()):
                    issues.append(f"{prefix}: outbound departure {outbound['departure']} falls outside date_window {date_window}")


def _check_hotel_data(plan: dict, prefix: str, issues: list[str],
                      warnings: list[str] | None = None) -> None:
    """Flag hotels with missing/zeroed core data.

    If a hotel name exists (meaning the Synthesizer tried to use real data),
    cost issues are downgraded to **warnings** — not hard rejections. Only
    a completely missing hotel section produces a hard issue.
    """
    if warnings is None:
        warnings = issues

    hotel = plan.get("hotel", {})
    if not isinstance(hotel, dict):
        return

    has_name = bool(hotel.get("name"))
    if not has_name:
        issues.append(f"{prefix}: missing hotel name")
        return

    total_cost = hotel.get("total_cost", 0)
    try:
        cost_val = float(total_cost) if total_cost else 0
    except (ValueError, TypeError):
        cost_val = 0

    per_night = hotel.get("per_night", 0)
    try:
        pn_val = float(per_night) if per_night else 0
    except (ValueError, TypeError):
        pn_val = 0

    # Hotel has a name but missing costs → warning, not a hard rejection
    target = warnings
    if cost_val <= 0:
        target.append(f"{prefix}: hotel total_cost is zero or missing")
    if pn_val <= 0:
        target.append(f"{prefix}: hotel per_night is zero or missing")

    # Ensure hotel is included in cost breakdown
    cost = plan.get("cost_breakdown", {})
    hotel_in_cost = cost.get("hotel", 0)
    try:
        if cost_val > 0 and (not hotel_in_cost or float(hotel_in_cost) <= 0):
            warnings.append(f"{prefix}: hotel has total_cost ${total_cost} but is not reflected in cost_breakdown.hotel")
    except (ValueError, TypeError):
        pass


def _check_itinerary_date_alignment(plan: dict, prefix: str, issues: list[str]) -> None:
    """Verify itinerary day count matches the date_window span."""
    itinerary = plan.get("itinerary", [])
    date_window = plan.get("date_window", "")

    if not itinerary or not isinstance(itinerary, list):
        return
    if not isinstance(date_window, str) or " to " not in date_window:
        return

    parts = date_window.split(" to ")
    win_start = _parse_dt(parts[0].strip())
    win_end = _parse_dt(parts[1].strip())
    if not win_start or not win_end:
        return

    expected_days = (win_end.date() - win_start.date()).days + 1
    actual_days = len(itinerary)

    if actual_days < expected_days - 1:
        issues.append(
            f"{prefix}: itinerary has {actual_days} days but date_window spans "
            f"{expected_days} days — {expected_days - actual_days} day(s) missing"
        )


def _cross_check_prices(plan: dict, state: SharedState, prefix: str, issues: list[str]) -> None:
    """Deterministic check: verify that flight/hotel prices in the package
    actually exist in the tool data. Catches LLM-fabricated prices.

    Flight prices may be multiplied by traveler count, so we check both
    the raw per-person price and common multiples (2-4 travelers).
    """
    flights = plan.get("flights", {})
    if isinstance(flights, dict):
        pkg_flight_cost = flights.get("total_flight_cost")
        if pkg_flight_cost:
            try:
                pkg_price = float(pkg_flight_cost)
                real_prices = {round(float(f.get("price", 0)), 2) for f in state.flight_options if f.get("price")}
                if real_prices:
                    # Allow exact match OR traveler multiples (1-4)
                    matched = any(
                        abs(pkg_price - rp * mult) < 5
                        for rp in real_prices
                        for mult in (1, 2, 3, 4)
                    )
                    if not matched:
                        issues.append(
                            f"{prefix}: flight cost ${pkg_price:.0f} not found in tool data "
                            f"(available per-person: ${min(real_prices):.0f}-${max(real_prices):.0f})"
                        )
            except (ValueError, TypeError):
                pass

    hotel = plan.get("hotel", {})
    if isinstance(hotel, dict):
        pkg_hotel_cost = hotel.get("total_cost")
        if pkg_hotel_cost:
            try:
                pkg_price = float(pkg_hotel_cost)
                real_prices = {round(float(h.get("total_price", 0)), 2) for h in state.hotel_options if h.get("total_price")}
                if real_prices and not any(abs(pkg_price - rp) < 10 for rp in real_prices):
                    issues.append(
                        f"{prefix}: hotel cost ${pkg_price:.0f} not found in tool data "
                        f"(available: ${min(real_prices):.0f}-${max(real_prices):.0f})"
                    )
            except (ValueError, TypeError):
                pass
