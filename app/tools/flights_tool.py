"""Flights tool -- search real-time flight prices via Booking.com Flights API (RapidAPI).

City-to-airport resolution is fully dynamic via the searchDestination endpoint.
Any city name worldwide is resolved automatically -- no hardcoded lookup tables.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx

# Maximum plausible nonstop flight duration (hours).
# Longest commercial nonstop is ~19h (Singapore-NYC). Use 20h as safe ceiling.
_MAX_NONSTOP_HOURS = 20

from app.config import RAPIDAPI_KEY
from app.models.shared_state import SharedState
from app.utils.cache import cache_get, cache_set, make_cache_key
from app.utils.step_logger import log_tool_call

_BASE_URL = "https://booking-com15.p.rapidapi.com/api/v1/flights"

_location_cache: dict[str, str] = {}


def _get_headers() -> dict[str, str]:
    return {
        "x-rapidapi-host": "booking-com15.p.rapidapi.com",
        "x-rapidapi-key": RAPIDAPI_KEY,
    }


def _resolve_flight_location(city_name: str, max_attempts: int = 3) -> str:
    """Resolve any city/airport name to a Booking.com flight location ID.

    Calls the searchDestination endpoint dynamically. Retries on transient
    failures. Caches results in-memory for the process lifetime.
    Returns the ID string (e.g. "TBS.AIRPORT") or the raw input as fallback.
    """
    key = city_name.strip().lower()
    if key in _location_cache:
        return _location_cache[key]

    for attempt in range(max_attempts):
        try:
            resp = httpx.get(
                f"{_BASE_URL}/searchDestination",
                headers=_get_headers(),
                params={"query": city_name},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())
            if isinstance(data, list) and data:
                loc_id = data[0].get("id", city_name)
                _location_cache[key] = loc_id
                return loc_id
        except Exception:
            if attempt < max_attempts - 1:
                time.sleep(0.5)

    _location_cache[key] = city_name
    return city_name


def search_flights(
    state: SharedState,
    origin: str,
    destination: str,
    date: str,
    return_date: str | None = None,
) -> list[dict[str, Any]]:
    """Search flights and store results in SharedState.

    Accepts any city name ("Tbilisi", "New York") or IATA code ("JFK").
    The resolver handles conversion dynamically via the Booking.com API.
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
        from_id = _resolve_flight_location(origin)
        to_id = _resolve_flight_location(destination)

        query_params: dict[str, str] = {
            "fromId": from_id,
            "toId": to_id,
            "departDate": date,
            "adults": "1",
            "sort": "CHEAPEST",
            "cabinClass": "ECONOMY",
            "currency_code": "USD",
        }
        if return_date:
            query_params["returnDate"] = return_date

        resp = httpx.get(
            f"{_BASE_URL}/searchFlights",
            headers=_get_headers(),
            params=query_params,
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()

        options = _parse_flight_results(raw, origin, destination, date, return_date)
        state.flight_options.extend(options)
        cache_set(ck, {"options": options})

        log_tool_call(state, "Executor", "flights_search", params,
                      {"count": len(options), "from_id": from_id, "to_id": to_id})
        return options

    except Exception as exc:
        log_tool_call(state, "Executor", "flights_search", params, {"error": str(exc)})
        return []


def _is_valid_flight(flight: dict[str, Any]) -> bool:
    """Filter out obviously invalid flight records.

    Catches:
    - Missing departure/arrival timestamps
    - Zero or negative duration
    - Nonstop flights with impossibly long durations (> 20 hours)
    - Arrival before departure when both parse cleanly
    """
    dep_str = flight.get("departure", "")
    arr_str = flight.get("arrival", "")

    if not dep_str or not arr_str:
        return False

    duration = flight.get("duration_minutes", 0)
    if duration <= 0:
        return False

    stops = flight.get("stops", 0)
    if stops == 0 and duration > _MAX_NONSTOP_HOURS * 60:
        return False

    dep_dt = _parse_iso_dt(dep_str)
    arr_dt = _parse_iso_dt(arr_str)
    if dep_dt and arr_dt and arr_dt < dep_dt:
        return False

    return True


def _parse_iso_dt(val: str) -> datetime | None:
    """Best-effort parse of ISO datetime strings from API."""
    if not val:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(val.strip()[:19], fmt)
        except ValueError:
            continue
    return None


def _parse_flight_results(
    raw: dict,
    origin_name: str,
    dest_name: str,
    depart_date: str,
    return_date: str | None,
) -> list[dict[str, Any]]:
    """Parse the Booking.com searchFlights response into flat flight dicts."""
    options: list[dict[str, Any]] = []
    data = raw.get("data", {})
    if not isinstance(data, dict):
        return options

    offers = data.get("flightOffers", [])
    for offer in offers[:10]:
        segments = offer.get("segments", [])
        if not segments:
            continue

        price_bd = offer.get("priceBreakdown", {})
        total_obj = price_bd.get("total", price_bd.get("totalRounded", {}))
        units = total_obj.get("units", 0)
        nanos = total_obj.get("nanos", 0)
        total_price = round(units + nanos / 1_000_000_000, 2)
        currency = total_obj.get("currencyCode", "USD")

        outbound = segments[0]
        ret_seg = segments[-1] if len(segments) > 1 else None

        out_legs = outbound.get("legs", [{}])
        out_leg = out_legs[0] if out_legs else {}

        dep_airport = outbound.get("departureAirport", {})
        arr_airport = outbound.get("arrivalAirport", {})
        carriers = out_leg.get("carriersData", [{}])
        airline = carriers[0].get("name", "") if carriers else ""

        from_code = dep_airport.get("code", "")
        to_code = arr_airport.get("code", "")

        flight = {
            "origin": from_code,
            "origin_city": dep_airport.get("cityName", origin_name),
            "destination": to_code,
            "destination_city": arr_airport.get("cityName", dest_name),
            "departure": outbound.get("departureTime", ""),
            "arrival": outbound.get("arrivalTime", ""),
            "duration_minutes": outbound.get("totalTime", 0) // 60 if outbound.get("totalTime") else 0,
            "stops": len(out_leg.get("flightStops", [])),
            "airline": airline,
            "price": total_price,
            "price_is": "roundtrip_total_per_person",
            "price_note": "This price is for 1 adult roundtrip. Multiply by number of travelers for group total.",
            "currency": currency,
            "trip_type": offer.get("tripType", "ROUNDTRIP"),
        }

        if ret_seg:
            flight["return_departure"] = ret_seg.get("departureTime", "")
            flight["return_arrival"] = ret_seg.get("arrivalTime", "")
            ret_dep = ret_seg.get("departureAirport", {})
            ret_arr = ret_seg.get("arrivalAirport", {})
            flight["return_from"] = ret_dep.get("code", "")
            flight["return_to"] = ret_arr.get("code", "")

        # Booking URL (Kayak-style deeplink)
        if from_code and to_code:
            url = f"https://booking.kayak.com/flights/{from_code}-{to_code}/{depart_date}"
            if return_date:
                url += f"/{return_date}"
            url += "?sort=bestflight_a"
            flight["booking_url"] = url

        # Filter out invalid flights before adding to results
        if _is_valid_flight(flight):
            options.append(flight)

    return options
