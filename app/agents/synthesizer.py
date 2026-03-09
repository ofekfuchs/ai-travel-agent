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
1. "label": "Best Value"
2. "destination": "City Name"
3. "date_window": "YYYY-MM-DD to YYYY-MM-DD" (MUST be a flat string, never an object)
4. "flights": {{
     "outbound": {{
       "origin": "ABC", "destination": "XYZ", "routing": "ABC → XYZ",
       "airline": "...", "departure": "ISO datetime", "arrival": "ISO datetime",
       "stops": N, "booking_url": "copy from flight data if available"
     }},
     "return": {{
       "origin": "XYZ", "destination": "ABC", "routing": "XYZ → ABC",
       "airline": "...", "departure": "ISO datetime", "arrival": "ISO datetime",
       "stops": N, "booking_url": "copy from flight data if available"
     }},
     "total_flight_cost": N,
     "trip_type": "ROUNDTRIP" or "ONEWAY"
   }}
5. "hotel": {{
     "name": "...", "address": "...", "rating": N,
     "per_night": N, "nights": N, "total_cost": N,
     "check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD",
     "booking_url": "copy from hotel data if available"
   }}
6. "weather_summary": "brief text"
7. "itinerary": [{{ "day": 1, "date": "YYYY-MM-DD", "activities": ["strings"] }}]
8. "cost_breakdown": {{ "flights": N, "hotel": N, "daily_expenses_estimate": N, "total": N }}
9. "rationale": "why this package fits"
10. "assumptions": ["list of caveats"]

CRITICAL RULES:
- Use ONLY real prices from the data provided. NEVER invent or fabricate prices.
- FLIGHT PRICING: Each flight's "price" field is the ROUNDTRIP TOTAL (both legs combined). The "price_is" field confirms this. Set "total_flight_cost" equal to the flight's "price" — do NOT double it.
- ALWAYS include BOTH outbound AND return flight details if the data provides return info (return_departure, return_arrival, return_from, return_to fields).
- Copy the "booking_url" from the selected flight/hotel data into the package.
- "date_window" MUST be a plain string like "2026-06-10 to 2026-06-17", NEVER an object.
- "assumptions" MUST be a JSON array of strings, e.g. ["note 1", "note 2"]. NEVER a single string.
- Hotel check-in must match flight arrival date, check-out must match departure.
- cost_breakdown.flights = total_flight_cost. cost_breakdown.total = flights + hotel + daily_expenses.
- Day 1 activities must be realistic given the arrival time. If arriving late at night, say "late arrival, check in to hotel" -- don't suggest sightseeing.
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
1. "label": "Budget Pick" / "Best Value" / "Premium"
2. "destination": "City Name"
3. "date_window": "YYYY-MM-DD to YYYY-MM-DD" (MUST be a flat string, never an object)
4. "flights": {{
     "outbound": {{
       "origin": "ABC", "destination": "XYZ", "routing": "ABC → XYZ",
       "airline": "...", "departure": "ISO datetime", "arrival": "ISO datetime",
       "stops": N, "booking_url": "copy from flight data if available"
     }},
     "return": {{
       "origin": "XYZ", "destination": "ABC", "routing": "XYZ → ABC",
       "airline": "...", "departure": "ISO datetime", "arrival": "ISO datetime",
       "stops": N, "booking_url": "copy from flight data if available"
     }},
     "total_flight_cost": N,
     "trip_type": "ROUNDTRIP" or "ONEWAY"
   }}
5. "hotel": {{
     "name": "...", "address": "...", "rating": N,
     "per_night": N, "nights": N, "total_cost": N,
     "check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD",
     "booking_url": "copy from hotel data if available"
   }}
6. "weather_summary": "brief text"
7. "itinerary": [{{ "day": 1, "date": "YYYY-MM-DD", "activities": ["strings"] }}]
8. "cost_breakdown": {{ "flights": N, "hotel": N, "daily_expenses_estimate": N, "total": N }}
9. "rationale": "why this package fits"
10. "assumptions": ["list of caveats"]

CRITICAL RULES:
- Use ONLY real prices from the data provided. NEVER invent or fabricate prices.
- FLIGHT PRICING: Each flight's "price" field is the ROUNDTRIP TOTAL (both legs combined). The "price_is" field confirms this. Set "total_flight_cost" equal to the flight's "price" — do NOT double it.
- ALWAYS include BOTH outbound AND return flight details if the data provides return info (return_departure, return_arrival, return_from, return_to fields).
- Copy the "booking_url" from the selected flight/hotel data into the package.
- "date_window" MUST be a plain string like "2026-06-10 to 2026-06-17", NEVER an object.
- "assumptions" MUST be a JSON array of strings, e.g. ["note 1", "note 2"]. NEVER a single string.
- Use DIFFERENT hotel/flight combos for each tier where possible.
- Hotel check-in must match flight arrival date, check-out must match departure.
- cost_breakdown.flights = total_flight_cost. cost_breakdown.total = flights + hotel + daily_expenses.
- Day 1 activities must be realistic given the arrival time. If arriving late at night, say "late arrival, check in to hotel" -- don't suggest sightseeing.
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
    """Generate booking links deterministically (zero LLM calls).

    Also pulls individual booking_url from the selected flight/hotel data
    into the package so the frontend can link directly to those results.
    """
    existing = pkg.get("booking_links") or {}
    has_flights_link = bool(existing.get("flights_search"))
    has_hotels_link = bool(existing.get("hotels_search"))

    if has_flights_link and has_hotels_link:
        return

    dest = pkg.get("destination", "")
    dates = pkg.get("date_window", "")
    if isinstance(dates, dict):
        depart = str(dates.get("start", dates.get("start_date", dates.get("from", ""))))
        ret = str(dates.get("end", dates.get("end_date", dates.get("to", ""))))
    else:
        date_parts = str(dates).split(" to ") if " to " in str(dates) else [str(dates), ""]
        depart = date_parts[0].strip()
        ret = date_parts[1].strip() if len(date_parts) > 1 else ""

    constraints = state.constraints or {}
    origin = constraints.get("origin", "")

    if not has_flights_link:
        flights_url = ""
        flight_data = pkg.get("flights", {})
        if isinstance(flight_data, dict):
            outbound = flight_data.get("outbound", {})
            flights_url = outbound.get("booking_url", "")

        if not flights_url and origin and dest and depart:
            flights_url = (
                f"https://www.google.com/travel/flights?q=Flights+from+"
                f"{urllib.parse.quote(origin)}+to+{urllib.parse.quote(dest)}"
                f"+on+{depart}" + (f"+returning+{ret}" if ret else "")
            )
        existing["flights_search"] = flights_url

    if not has_hotels_link:
        hotels_url = ""
        hotel_data = pkg.get("hotel", {})
        if isinstance(hotel_data, dict):
            hotels_url = hotel_data.get("booking_url", "")

        if not hotels_url and dest and depart and ret:
            hotels_url = (
                f"https://www.booking.com/searchresults.html?"
                f"ss={urllib.parse.quote(dest)}&checkin={depart}&checkout={ret}"
                f"&group_adults=1&no_rooms=1"
            )
        existing["hotels_search"] = hotels_url

    pkg["booking_links"] = existing


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
