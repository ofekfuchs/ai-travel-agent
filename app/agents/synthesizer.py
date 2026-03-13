"""Trip Synthesizer -- assembles packages from real tool data.

Uses flat flight_options / hotel_options / weather / POIs from SharedState.
Booking links are generated deterministically (zero LLM).
"""

from __future__ import annotations

import json
import urllib.parse

from app.config import RAG_DISPLAY_CHARS_SYNTH, RAG_MAX_CHUNKS_SYNTH
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
- NEVER create packages for destinations that have NO FLIGHTS in the data. If a city only has hotels/weather but zero flights, SKIP that city entirely.
- NEVER fabricate transport modes (drive, train, bus, ferry). If the data does not contain a real flight for a destination, do NOT include that destination.
- FLIGHT PRICING POLICY:
  * Each flight's "price" is the ROUNDTRIP TOTAL for ONE person (both legs combined).
  * The "price_is" field confirms this is per-person.
  * If the user has multiple travelers, "total_flight_cost" = price × number_of_travelers.
  * If the user has 1 traveler (or unspecified), "total_flight_cost" = price as-is.
  * Always state in assumptions: "Flight prices are per person; total reflects N traveler(s)."
- HOTEL PRICING POLICY:
  * Hotel "total_price" is the total for the entire stay (1 room). Use it directly as hotel total_cost.
  * per_night = total_price / number_of_nights. NEVER leave per_night or total_cost as 0.
  * Do NOT multiply hotel cost by travelers — it is per room.
  * CRITICAL: hotel total_cost and per_night MUST be positive numbers copied from the data.
- ALWAYS include BOTH outbound AND return flight details if the data provides return info (return_departure, return_arrival, return_from, return_to fields).
- Copy the "booking_url" from the selected flight/hotel data into the package.
- "date_window" MUST be a plain string like "2026-06-10 to 2026-06-17", NEVER an object.
- "assumptions" MUST be a JSON array of strings, e.g. ["note 1", "note 2"]. NEVER a single string.
- Hotel check-in must match flight arrival date, check-out must match departure.
- cost_breakdown.flights = total_flight_cost (already multiplied by travelers).
- cost_breakdown.hotel = hotel total_cost (per room, used directly).
- cost_breakdown.daily_expenses_estimate = estimated daily expenses for ALL travelers combined.
- cost_breakdown.total = flights + hotel + daily_expenses.
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

CROSS-DESTINATION RULE: When data for MULTIPLE DESTINATIONS is provided, you
MUST create packages from DIFFERENT destinations to give the user variety.
For example: Budget Pick from Budapest, Best Value from Berlin, Premium from
Lisbon. Do NOT put all packages in the same city when alternatives exist!

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
- NEVER create packages for destinations that have NO FLIGHTS in the data. If a city only has hotels/weather but zero flights, SKIP that city entirely.
- NEVER fabricate transport modes (drive, train, bus, ferry). If the data does not contain a real flight for a destination, do NOT include that destination.
- FLIGHT PRICING POLICY:
  * Each flight's "price" is the ROUNDTRIP TOTAL for ONE person (both legs combined).
  * The "price_is" field confirms this is per-person.
  * If the user has multiple travelers, "total_flight_cost" = price × number_of_travelers.
  * If the user has 1 traveler (or unspecified), "total_flight_cost" = price as-is.
  * Always state in assumptions: "Flight prices are per person; total reflects N traveler(s)."
- HOTEL PRICING POLICY:
  * Hotel "total_price" is the total for the entire stay (1 room). Use it directly as hotel total_cost.
  * per_night = total_price / number_of_nights. NEVER leave per_night or total_cost as 0.
  * Do NOT multiply hotel cost by travelers — it is per room.
  * CRITICAL: hotel total_cost and per_night MUST be positive numbers copied from the data.
- ALWAYS include BOTH outbound AND return flight details if the data provides return info (return_departure, return_arrival, return_from, return_to fields).
- Copy the "booking_url" from the selected flight/hotel data into the package.
- "date_window" MUST be a plain string like "2026-06-10 to 2026-06-17", NEVER an object.
- "assumptions" MUST be a JSON array of strings, e.g. ["note 1", "note 2"]. NEVER a single string.
- Use DIFFERENT hotel/flight combos for each tier where possible.
- Hotel check-in must match flight arrival date, check-out must match departure.
- cost_breakdown.flights = total_flight_cost (already multiplied by travelers).
- cost_breakdown.hotel = hotel total_cost (per room, used directly).
- cost_breakdown.daily_expenses_estimate = estimated daily expenses for ALL travelers combined.
- cost_breakdown.total = flights + hotel + daily_expenses.
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
        _patch_hotel_costs(pkg, state)
        _ensure_booking_links(pkg, state)
        _ensure_poi_links(pkg, state)

    state.draft_plans = packages


def _build_prompt(state: SharedState) -> str:
    """Build user prompt from tool-output lists in SharedState.

    Groups data by destination so the LLM sees each city's flights, hotels,
    weather, and POIs together — enabling proper cross-destination comparison.
    """
    parts = [f"User request: {state.raw_prompt}"]

    if state.constraints:
        parts.append(f"Constraints: {json.dumps(state.constraints, default=str)}")

    if state.destination_chunks:
        dest_rag = _group_rag_by_destination(state)
        if dest_rag:
            rag_parts = ["Destination knowledge from Wikivoyage (use for itinerary grounding):"]
            for dest_name, chunks in dest_rag.items():
                rag_parts.append(f"\n  [{dest_name}]")
                for c in chunks[:RAG_MAX_CHUNKS_SYNTH]:
                    section = c.get("section_name", "general")
                    rag_parts.append(f"  - ({section}) {c.get('content', '')[:RAG_DISPLAY_CHARS_SYNTH]}")
            parts.append("\n".join(rag_parts))
        else:
            summaries = [
                f"- {c.get('article_title', '?')}: {c.get('content', '')[:RAG_DISPLAY_CHARS_SYNTH]}"
                for c in state.destination_chunks[:RAG_MAX_CHUNKS_SYNTH]
            ]
            parts.append("Destination knowledge:\n" + "\n".join(summaries))

    grouped = _group_data_by_destination(state)

    if grouped:
        dest_names = list(grouped.keys())
        parts.append(f"Data available for {len(dest_names)} destination(s): {', '.join(dest_names)}")

        for dest_name, dest_data in grouped.items():
            section = [f"\n=== {dest_name} ==="]

            flights = dest_data["flights"]
            if flights:
                top = sorted(flights, key=lambda f: f.get("price", 9999))[:5]
                section.append(f"Flights ({len(flights)} options, top 5): {json.dumps(top, default=str)}")
            else:
                section.append("Flights: none found")

            hotels = dest_data["hotels"]
            if hotels:
                top = sorted(hotels, key=lambda h: h.get("total_price", 9999))[:5]
                section.append(f"Hotels ({len(hotels)} options, top 5): {json.dumps(top, default=str)}")
            else:
                section.append("Hotels: none found")

            weather = dest_data["weather"]
            if weather:
                section.append(f"Weather: {json.dumps(weather[0], default=str)}")

            pois = dest_data["pois"]
            if pois:
                named = [p for p in pois if p.get("name") and p["name"] != "Unnamed"][:5]
                if named:
                    section.append(f"POIs: {json.dumps(named, default=str)}")

            parts.append("\n".join(section))
    else:
        if state.flight_options:
            flight_dests = {f.get("destination_city") or f.get("destination", "") for f in state.flight_options}
            sf = sorted(state.flight_options, key=lambda f: f.get("price", 9999))[:8]
            parts.append(f"Flight options ({len(state.flight_options)} total, 8 cheapest): "
                         f"{json.dumps(sf, default=str)}")

            reachable_hotels = [h for h in state.hotel_options
                                if h.get("destination_city", "") in flight_dests]
            if reachable_hotels:
                sh = sorted(reachable_hotels, key=lambda h: h.get("total_price", 9999))[:8]
                parts.append(f"Hotel options ({len(reachable_hotels)} in flight-reachable cities, 8 cheapest): "
                             f"{json.dumps(sh, default=str)}")
            elif state.hotel_options:
                sh = sorted(state.hotel_options, key=lambda h: h.get("total_price", 9999))[:8]
                parts.append(f"Hotel options ({len(state.hotel_options)} total, 8 cheapest): "
                             f"{json.dumps(sh, default=str)}")
            else:
                parts.append("Hotel options: NONE FOUND (do not invent hotel prices)")
        else:
            parts.append("Flight options: NONE FOUND (do not invent flight prices)")
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


def _group_rag_by_destination(state: SharedState) -> dict[str, list[dict]]:
    """Group RAG chunks by their article_title, matching against destinations
    that have flight data. Returns only destination-relevant chunks so the
    Synthesizer gets specific Wikivoyage knowledge per city."""
    flight_dests = {
        (f.get("destination_city") or f.get("destination", "")).lower()
        for f in state.flight_options
        if f.get("destination_city") or f.get("destination")
    }

    grouped: dict[str, list[dict]] = {}
    for chunk in state.destination_chunks:
        title = chunk.get("article_title", "")
        if title.lower() in flight_dests:
            grouped.setdefault(title, []).append(chunk)

    return grouped


def _group_data_by_destination(state: SharedState) -> dict[str, dict]:
    """Group flights/hotels/weather/POIs by destination city.

    Returns {city_name: {"flights": [...], "hotels": [...], "weather": [...], "pois": [...]}}
    ONLY includes destinations that have real flight data — destinations
    with 0 flights are excluded to prevent fabricated drive/train packages.
    """
    grouped: dict[str, dict] = {}

    for f in state.flight_options:
        dest = f.get("destination_city") or f.get("destination", "")
        if not dest:
            continue
        grouped.setdefault(dest, {"flights": [], "hotels": [], "weather": [], "pois": []})
        grouped[dest]["flights"].append(f)

    for h in state.hotel_options:
        dest = h.get("destination_city", "")
        if not dest or dest not in grouped:
            continue
        grouped[dest]["hotels"].append(h)

    for w in state.weather_context:
        dest = w.get("destination", "")
        if dest in grouped:
            grouped[dest]["weather"].append(w)

    for p in state.poi_list:
        dest = p.get("destination", "")
        if dest in grouped:
            grouped[dest]["pois"].append(p)

    grouped = {d: v for d, v in grouped.items() if v["flights"]}

    if not grouped:
        return {}

    return grouped


def _patch_hotel_costs(pkg: dict, state: SharedState) -> None:
    """Deterministic fix: if the LLM left hotel costs at 0 or missing, look up
    the matching hotel in state.hotel_options and fill in the real price."""
    hotel = pkg.get("hotel")
    if not isinstance(hotel, dict) or not hotel.get("name"):
        return

    try:
        total = float(hotel.get("total_cost") or 0)
    except (ValueError, TypeError):
        total = 0

    if total > 0:
        return

    hotel_name = hotel["name"].lower().strip()
    dest = (pkg.get("destination") or "").lower().strip()

    best_match = None
    for h in state.hotel_options:
        h_name = (h.get("name") or "").lower().strip()
        h_dest = (h.get("destination_city") or "").lower().strip()
        h_price = h.get("total_price", 0)
        try:
            h_price = float(h_price)
        except (ValueError, TypeError):
            continue
        if h_price <= 0:
            continue

        if h_name == hotel_name:
            best_match = h
            break
        if dest and h_dest == dest and best_match is None:
            best_match = h

    if best_match:
        real_total = float(best_match.get("total_price", 0))
        nights = hotel.get("nights") or 1
        try:
            nights = int(nights) if int(nights) > 0 else 1
        except (ValueError, TypeError):
            nights = 1

        hotel["total_cost"] = round(real_total, 2)
        per_night = real_total / nights
        hotel["per_night"] = round(per_night, 2)

        cost = pkg.get("cost_breakdown")
        if isinstance(cost, dict):
            cost["hotel"] = round(real_total, 2)
            flights_cost = cost.get("flights", 0)
            daily = cost.get("daily_expenses_estimate", 0)
            try:
                cost["total"] = round(float(flights_cost) + real_total + float(daily), 2)
            except (ValueError, TypeError):
                pass


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
            travelers = constraints.get("travelers") or 1
            hotels_url = (
                f"https://www.booking.com/searchresults.html?"
                f"ss={urllib.parse.quote(dest)}&checkin={depart}&checkout={ret}"
                f"&group_adults={travelers}&no_rooms=1"
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
