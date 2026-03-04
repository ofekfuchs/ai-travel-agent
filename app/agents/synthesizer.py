"""Trip Synthesizer -- assembles packages from real tool data.

Uses flat flight_options / hotel_options / weather / POIs from SharedState.
Booking links are generated deterministically (zero LLM).
"""

from __future__ import annotations

import json
import urllib.parse

from app.llm.client import call_llm
from app.models.shared_state import SharedState

_SYSTEM_PROMPT_SINGLE = """\
You are the Trip Synthesizer. You receive REAL pricing data from tool APIs.
Build ONE package -- the cheapest that fits the user's request.

The package MUST include ALL of these fields:
1. "destination" and "date_window" (e.g. "2026-06-15 to 2026-06-19")
2. "flights" with outbound/return details and prices FROM THE DATA PROVIDED
3. "hotel" with name, per_night price, total FROM THE DATA PROVIDED
4. "weather_summary"
5. "itinerary" - day-by-day activities
6. "cost_breakdown" with {{ "flights": N, "hotel": N, "daily_expenses_estimate": N, "total": N }}
7. "rationale" - why this package fits the user (mention price trade-offs)
8. "assumptions" - any caveats or limitations

CRITICAL RULES:
- Use ONLY real prices from the data provided. NEVER invent or fabricate prices.
- If data for a field is missing, explicitly state "data not available" instead of making up values.
- Pick the CHEAPEST flight+hotel from the data.
- Hotel check-in must match flight arrival date, check-out must match departure.
- cost_breakdown.total must be an actual sum of its components.
- If the cheapest combination exceeds the budget, explain the gap and the
  dominant cost driver.
- Label: "Best Value".
- Return {{ "packages": [ {{ ... }} ] }}
- Return ONLY valid JSON, no markdown.
"""

_SYSTEM_PROMPT_MULTI = """\
You are the Trip Synthesizer. You receive REAL pricing data from tool APIs.
Build 2-3 packages at different tiers:

1. "Budget Pick"  -- cheapest viable option
2. "Best Value"   -- best balance of price and quality
3. "Premium" (optional, only if data supports it)

Each package MUST include ALL of these fields:
1. "label" (e.g. "Budget Pick", "Best Value", "Premium")
2. "destination" and "date_window"
3. "flights" with outbound/return details and prices FROM THE DATA PROVIDED
4. "hotel" with name, per_night price, total FROM THE DATA PROVIDED
5. "weather_summary"
6. "itinerary" - day-by-day activities
7. "cost_breakdown" with {{ "flights": N, "hotel": N, "daily_expenses_estimate": N, "total": N }}
8. "rationale" - why this package fits the user
9. "assumptions" - any caveats

CRITICAL RULES:
- Use ONLY real prices from the data provided. NEVER invent or fabricate prices.
- If data for a field is missing, explicitly state "data not available" instead of making up values.
- Use DIFFERENT hotel/flight combos for each tier where possible.
- cost_breakdown.total must be an actual sum of its components.
- Return {{ "packages": [ {{ ... }}, {{ ... }} ] }}
- Return ONLY valid JSON, no markdown.
"""


def run_synthesizer(state: SharedState, tight_budget: bool = False) -> None:
    """Build trip package(s) from real tool data in SharedState."""
    system_prompt = _SYSTEM_PROMPT_SINGLE if tight_budget else _SYSTEM_PROMPT_MULTI
    user_prompt = _build_prompt(state)

    raw = call_llm(
        state,
        module="Trip Synthesizer",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    try:
        result = json.loads(raw)
        packages = result.get("packages", [result])
    except json.JSONDecodeError:
        packages = [{"raw_text": raw, "parse_error": True}]

    for pkg in packages:
        _ensure_booking_links(pkg, state)
        _ensure_poi_links(pkg, state)

    state.draft_plans = packages


def _build_prompt(state: SharedState) -> str:
    """Build user prompt from flat tool-output lists in SharedState."""
    parts = [f"User request: {state.raw_prompt}"]

    if state.constraints:
        parts.append(f"Constraints: {json.dumps(state.constraints, default=str)}")

    if state.destination_chunks:
        summaries = [
            f"- {c.get('article_title', '?')}: {c.get('content', '')[:150]}"
            for c in state.destination_chunks[:5]
        ]
        parts.append("Destination knowledge:\n" + "\n".join(summaries))

    if state.flight_options:
        sf = sorted(state.flight_options, key=lambda f: f.get("price", 9999))[:8]
        parts.append(f"Flight options ({len(state.flight_options)} total, 8 cheapest): "
                     f"{json.dumps(sf, default=str)}")
    else:
        parts.append("Flight options: NONE FOUND (do not invent flight prices)")

    if state.hotel_options:
        sh = sorted(state.hotel_options, key=lambda h: h.get("total_price", 9999))[:8]
        parts.append(f"Hotel options ({len(state.hotel_options)} total, 8 cheapest): "
                     f"{json.dumps(sh, default=str)}")
    else:
        parts.append("Hotel options: NONE FOUND (do not invent hotel prices)")

    if state.weather_context:
        parts.append(f"Weather: {json.dumps(state.weather_context[:3], default=str)}")

    if state.poi_list:
        named = [p for p in state.poi_list
                 if p.get("name") and p["name"] != "Unnamed"][:10]
        parts.append(f"POIs ({len(state.poi_list)} found): {json.dumps(named, default=str)}")

    if state.verifier_verdicts:
        last = state.verifier_verdicts[-1]
        parts.append(
            f"PREVIOUS REJECTION ISSUES (fix these specifically): "
            f"{json.dumps(last.get('issues', []), default=str)}"
        )

    return "\n\n".join(parts)


def _ensure_booking_links(pkg: dict, state: SharedState) -> None:
    """Generate booking links deterministically (zero LLM calls)."""
    if pkg.get("booking_links"):
        return

    dest = pkg.get("destination", "")
    dates = pkg.get("date_window", "")
    constraints = state.constraints or {}
    origin = constraints.get("origin", "")
    date_parts = dates.split(" to ") if " to " in dates else ["", ""]
    depart = date_parts[0].strip()
    ret = date_parts[1].strip() if len(date_parts) > 1 else ""

    flights_url = ""
    if origin and dest and depart:
        flights_url = (
            f"https://www.google.com/travel/flights?q=Flights+from+"
            f"{urllib.parse.quote(origin)}+to+{urllib.parse.quote(dest)}"
            f"+on+{depart}" + (f"+returning+{ret}" if ret else "")
        )

    hotels_url = ""
    if dest and depart and ret:
        hotels_url = (
            f"https://www.booking.com/searchresults.html?"
            f"ss={urllib.parse.quote(dest)}&checkin={depart}&checkout={ret}"
            f"&group_adults=1&no_rooms=1"
        )

    pkg["booking_links"] = {
        "flights_search": flights_url,
        "hotels_search": hotels_url,
    }


def _ensure_poi_links(pkg: dict, state: SharedState) -> None:
    """Attach Google Maps / OpenTripMap links to itinerary activities."""
    poi_map: dict[str, dict] = {}
    for poi in state.poi_list:
        name = poi.get("name", "")
        if name and name != "Unnamed":
            poi_map[name.lower()] = poi

    itinerary = pkg.get("itinerary")
    if not itinerary or not isinstance(itinerary, list):
        return

    for day in itinerary:
        activities = day.get("activities") if isinstance(day, dict) else None
        if not activities or not isinstance(activities, list):
            continue
        for act in activities:
            if not isinstance(act, dict):
                continue
            act_name = (act.get("name") or act.get("activity") or "").lower()
            for poi_name, poi_data in poi_map.items():
                if poi_name in act_name or act_name in poi_name:
                    lat = poi_data.get("lat")
                    lon = poi_data.get("lon")
                    if lat and lon:
                        act["google_maps_link"] = f"https://www.google.com/maps?q={lat},{lon}"
                    xid = poi_data.get("xid")
                    if xid:
                        act["opentripmap_link"] = f"https://opentripmap.io/en/card/{xid}"
                    break
