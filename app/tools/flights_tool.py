"""Flights tool -- search real-time flight prices via Flights Sky API (RapidAPI).

Handles city-name-to-IATA resolution automatically via the auto-complete endpoint,
so callers can pass either "New York" or "JFK" and it will work.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import RAPIDAPI_KEY
from app.models.shared_state import SharedState
from app.utils.cache import cache_get, cache_set, make_cache_key
from app.utils.step_logger import log_tool_call

_BASE_URL = "https://flights-sky.p.rapidapi.com"
_HEADERS = {
    "x-rapidapi-host": "flights-sky.p.rapidapi.com",
    "x-rapidapi-key": "",
}

_CITY_TO_SKY_ID: dict[str, str] = {
    "new york": "NYCA",
    "new york city": "NYCA",
    "paris": "PARI",
    "london": "LOND",
    "berlin": "BERL",
    "washington": "WASH",
    "washington dc": "WASH",
    "washington d.c.": "WASH",
    "rome": "ROME",
    "tokyo": "TYOA",
    "barcelona": "BCN",
    "amsterdam": "AMS",
    "prague": "PRG",
    "vienna": "VIE",
    "lisbon": "LIS",
    "tel aviv": "TLV",
    "los angeles": "LAXA",
    "chicago": "CHIA",
    "san francisco": "SFOA",
    "miami": "MIAA",
    "bangkok": "BKKT",
    "dubai": "DXBA",
    "istanbul": "ISTA",
    "athens": "ATH",
    "madrid": "MAD",
    "munich": "MUC",
    "sydney": "SYDA",
    "toronto": "YTO",
}


def _get_headers() -> dict[str, str]:
    return {
        "x-rapidapi-host": "flights-sky.p.rapidapi.com",
        "x-rapidapi-key": RAPIDAPI_KEY,
    }


def _resolve_entity_id(query: str) -> str:
    """Convert a city name to a Flights Sky skyId.

    Uses a static lookup table for common cities (zero API calls).
    If not found, returns the query as-is (works for IATA codes like JFK, CDG).
    """
    key = query.strip().lower()
    if key in _CITY_TO_SKY_ID:
        return _CITY_TO_SKY_ID[key]
    return query


def search_flights(
    state: SharedState,
    origin: str,
    destination: str,
    date: str,
    return_date: str | None = None,
) -> list[dict[str, Any]]:
    """Search one-way or round-trip flights and store results in Shared State.

    Accepts city names ("New York") or IATA codes ("JFK") -- the resolver
    handles conversion automatically.
    """
    params: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "date": date,
    }
    if return_date:
        params["return_date"] = return_date

    ck = make_cache_key("flights", params)
    cached = cache_get(ck)
    if cached is not None:
        state.flight_options.extend(cached.get("options", []))
        log_tool_call(state, "Executor", "flights_search", params,
                      {"source": "cache", "count": len(cached.get("options", []))})
        return cached.get("options", [])

    if not RAPIDAPI_KEY:
        log_tool_call(state, "Executor", "flights_search", params,
                      {"error": "RAPIDAPI_KEY not configured"})
        return []

    try:
        origin_id = _resolve_entity_id(origin)
        dest_id = _resolve_entity_id(destination)

        endpoint = f"{_BASE_URL}/flights/search-one-way"
        query_params: dict[str, str] = {
            "fromEntityId": origin_id,
            "toEntityId": dest_id,
            "departDate": date,
        }
        if return_date:
            endpoint = f"{_BASE_URL}/flights/search-roundtrip"
            query_params["returnDate"] = return_date

        resp = httpx.get(endpoint, headers=_get_headers(), params=query_params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        options = _parse_flight_results(data)
        state.flight_options.extend(options)
        cache_set(ck, {"options": options})

        log_tool_call(state, "Executor", "flights_search", params,
                      {"count": len(options), "resolved_origin": origin_id, "resolved_dest": dest_id})
        return options

    except Exception as exc:
        log_tool_call(state, "Executor", "flights_search", params, {"error": str(exc)})
        return []


def _parse_flight_results(raw: dict) -> list[dict[str, Any]]:
    """Extract a flat list of flight options from the API response."""
    options: list[dict[str, Any]] = []
    data = raw.get("data", {})
    if not isinstance(data, dict):
        return options

    for itinerary in data.get("itineraries", []):
        price_raw = itinerary.get("price", {}).get("raw", 0)
        legs = itinerary.get("legs", [])
        for leg in legs:
            carriers = leg.get("carriers", {})
            marketing = carriers.get("marketing", [{}])
            airline = marketing[0].get("name", "") if marketing else ""
            options.append(
                {
                    "origin": leg.get("origin", {}).get("displayCode", ""),
                    "destination": leg.get("destination", {}).get("displayCode", ""),
                    "departure": leg.get("departure", ""),
                    "arrival": leg.get("arrival", ""),
                    "duration_minutes": leg.get("durationInMinutes", 0),
                    "stops": leg.get("stopCount", 0),
                    "airline": airline,
                    "price": price_raw,
                }
            )
    return options[:10]
