"""Trip Synthesizer -- assembles collected tool outputs into one or more
coherent, internally consistent trip packages.

Optimizations:
- Receives budget_warning if the pre-check found the budget is tight
- Receives Verifier feedback on re-plans so it fixes specific issues
- Generates booking links for flights and hotels
- Builds ONLY 1 package to save tokens (not 2-3)
"""

from __future__ import annotations

import json
import urllib.parse

from app.llm.client import call_llm
from app.models.shared_state import SharedState

SYSTEM_PROMPT = """\
You are the Trip Synthesizer. You receive structured travel data and must
assemble ONE complete trip package (the best-fit for the user's constraints).

The package MUST include ALL of these fields:
1. "destination" and "date_window"
2. "flights" with outbound/return details and prices FROM THE DATA
3. "hotel" with name, per_night price, total FROM THE DATA
4. "weather_summary"
5. "itinerary" - day-by-day activities
6. "cost_breakdown" with flights, hotel, daily_expenses_estimate, total
7. "rationale" - why this fits the user
8. "assumptions" - any caveats
9. "booking_links" - object with "flights_search" and "hotels_search" URLs

CRITICAL RULES:
- Use ONLY real prices from the provided flight and hotel data.
  Do NOT invent prices. Pick the cheapest options that fit.
- If the budget is tight, pick the CHEAPEST flight and hotel.
  Explain the budget gap honestly in rationale.
- Hotel check-in must match arrival date, check-out must match departure date.
- For booking_links, generate:
  - flights_search: Google Flights URL for the route and dates
  - hotels_search: Booking.com URL for the destination and dates
- Build only ONE package (label: "Best Match").
- Return a JSON object: { "packages": [ { ... } ] }
- Return ONLY valid JSON, no markdown.
"""


def run_synthesizer(state: SharedState) -> None:
    """Build trip package from Shared State data."""
    data_parts = [f"User request: {state.raw_prompt}"]

    if state.constraints:
        data_parts.append(f"Constraints: {json.dumps(state.constraints, default=str)}")

    if state.budget_warning:
        data_parts.append(f"BUDGET WARNING: {state.budget_warning}")

    if state.destination_chunks:
        summaries = [
            f"- {c.get('article_title', '?')} ({c.get('section_name', '?')}): {c.get('content', '')[:200]}"
            for c in state.destination_chunks[:5]
        ]
        data_parts.append("Destination knowledge:\n" + "\n".join(summaries))

    if state.flight_options:
        sorted_flights = sorted(state.flight_options, key=lambda f: f.get("price", 9999))[:6]
        data_parts.append(f"Flight options ({len(state.flight_options)} total, showing 6 cheapest): {json.dumps(sorted_flights, default=str)}")

    if state.hotel_options:
        sorted_hotels = sorted(state.hotel_options, key=lambda h: h.get("total_price", 9999))[:6]
        data_parts.append(f"Hotel options ({len(state.hotel_options)} total, showing 6 cheapest): {json.dumps(sorted_hotels, default=str)}")

    if state.weather_context:
        data_parts.append(f"Weather context: {json.dumps(state.weather_context[:2], default=str)}")

    if state.poi_list:
        named_pois = [p for p in state.poi_list if p.get("name") and p["name"] != "Unnamed"][:8]
        data_parts.append(f"Points of interest ({len(state.poi_list)} found): {json.dumps(named_pois, default=str)}")

    if state.verifier_verdicts:
        last = state.verifier_verdicts[-1]
        data_parts.append(
            f"PREVIOUS REJECTION ISSUES (fix these specifically): "
            f"{json.dumps(last.get('issues', []), default=str)}"
        )

    user_prompt = "\n\n".join(data_parts)

    raw = call_llm(
        state,
        module="Trip Synthesizer",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    try:
        result = json.loads(raw)
        packages = result.get("packages", [result])
    except json.JSONDecodeError:
        packages = [{"raw_text": raw, "parse_error": True}]

    for pkg in packages:
        _ensure_booking_links(pkg, state)

    state.draft_plans = packages


def _ensure_booking_links(pkg: dict, state: SharedState) -> None:
    """Add booking search links if the LLM didn't generate them."""
    if pkg.get("booking_links"):
        return

    dest = pkg.get("destination", "")
    dates = pkg.get("date_window", "")
    constraints = state.constraints or {}

    origin = constraints.get("origin", "")
    parts = dates.split(" to ") if " to " in dates else ["", ""]
    depart = parts[0].strip()
    ret = parts[1].strip() if len(parts) > 1 else ""

    flights_url = ""
    if origin and dest and depart:
        flights_url = (
            f"https://www.google.com/travel/flights?q=Flights+from+"
            f"{urllib.parse.quote(origin)}+to+{urllib.parse.quote(dest)}"
            f"+on+{depart}"
            + (f"+returning+{ret}" if ret else "")
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
