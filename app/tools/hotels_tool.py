"""Hotels tool -- search hotel options via RapidAPI Booking.com provider.

Handles city-name-to-dest_id resolution automatically via the
searchDestination endpoint, so callers can pass "Paris" directly.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from app.config import RAPIDAPI_KEY
from app.models.shared_state import SharedState
from app.utils.cache import cache_get, cache_set, make_cache_key
from app.utils.step_logger import log_tool_call

_BASE_URL = "https://booking-com15.p.rapidapi.com/api/v1/hotels"

_dest_cache: dict[str, tuple[str, str]] = {}


def _get_headers() -> dict[str, str]:
    return {
        "x-rapidapi-host": "booking-com15.p.rapidapi.com",
        "x-rapidapi-key": RAPIDAPI_KEY,
    }


def _resolve_dest_id(city_name: str) -> tuple[str, str]:
    """Convert a city name to a Booking.com (dest_id, dest_type) pair.

    Uses the searchDestination endpoint. Caches in-memory within one session.
    Returns (dest_id, dest_type) or (city_name, "CITY") as fallback.
    """
    key = city_name.strip().lower()
    if key in _dest_cache:
        return _dest_cache[key]

    try:
        resp = httpx.get(
            f"{_BASE_URL}/searchDestination",
            headers=_get_headers(),
            params={"query": city_name},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        destinations = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(destinations, list) and destinations:
            first = destinations[0]
            dest_id = str(first.get("dest_id", ""))
            dest_type = first.get("dest_type", first.get("search_type", "CITY"))
            _dest_cache[key] = (dest_id, dest_type.upper())
            return _dest_cache[key]
    except Exception:
        pass

    _dest_cache[key] = (city_name, "CITY")
    return _dest_cache[key]


def search_hotels(
    state: SharedState,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
) -> list[dict[str, Any]]:
    """Search hotels near *destination* for the given dates.

    Accepts plain city names ("Paris") -- the resolver handles conversion
    to a Booking.com dest_id automatically.
    """
    params = {
        "destination": destination,
        "check_in": check_in,
        "check_out": check_out,
        "adults": adults,
    }

    ck = make_cache_key("hotels", params)
    cached = cache_get(ck)
    if cached is not None:
        state.hotel_options.extend(cached.get("options", []))
        log_tool_call(state, "Executor", "hotels_search", params,
                      {"source": "cache", "count": len(cached.get("options", []))})
        return cached.get("options", [])

    if not RAPIDAPI_KEY:
        log_tool_call(state, "Executor", "hotels_search", params,
                      {"error": "RAPIDAPI_KEY not configured"})
        return []

    try:
        dest_id, dest_type = _resolve_dest_id(destination)

        search_params = {
            "dest_id": dest_id,
            "search_type": dest_type,
            "arrival_date": check_in,
            "departure_date": check_out,
            "adults": str(adults),
            "room_qty": "1",
            "page_number": "1",
            "units": "metric",
            "temperature_unit": "c",
            "languagecode": "en-us",
            "currency_code": "USD",
        }

        resp = httpx.get(
            f"{_BASE_URL}/searchHotels",
            headers=_get_headers(),
            params=search_params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        options = _parse_hotel_results(data, check_in, check_out)
        state.hotel_options.extend(options)
        cache_set(ck, {"options": options})

        log_tool_call(state, "Executor", "hotels_search", params,
                      {"count": len(options), "resolved_dest_id": dest_id})
        return options

    except Exception as exc:
        log_tool_call(state, "Executor", "hotels_search", params, {"error": str(exc)})
        return []


def _parse_hotel_results(raw: dict, check_in: str, check_out: str) -> list[dict[str, Any]]:
    """Flatten the API response into a list of hotel option dicts.

    The Booking.com API returns hotels under data.hotels (newer format)
    or data.result (older format). Each hotel object wraps details in
    a 'property' sub-object.
    """
    options: list[dict[str, Any]] = []
    data = raw.get("data", {})
    if not isinstance(data, dict):
        return options

    result_list = data.get("hotels", data.get("result", []))
    if not isinstance(result_list, list):
        return options

    nights = _days_between(check_in, check_out)

    for hotel in result_list:
        prop = hotel.get("property", {})

        price_bd = prop.get("priceBreakdown", {})
        total_price = price_bd.get("grossPrice", {}).get("value", 0)
        if not total_price:
            total_price = hotel.get("min_total_price", 0)

        name = prop.get("name", hotel.get("hotel_name", "Unknown"))
        rating = prop.get("reviewScore", hotel.get("review_score", 0))

        if total_price:
            total_price = round(total_price, 2)

        booking_url = _build_hotel_url(name, check_in, check_out)

        options.append(
            {
                "name": name,
                "check_in": check_in,
                "check_out": check_out,
                "price_per_night": round(total_price / nights, 2) if total_price else 0,
                "total_price": total_price,
                "currency": "USD",
                "rating": rating,
                "address": prop.get("wishlistName", ""),
                "booking_url": booking_url,
            }
        )
    return options[:10]


def _build_hotel_url(name: str, check_in: str, check_out: str) -> str:
    """Construct a Booking.com search URL that leads to this hotel."""
    return (
        f"https://www.booking.com/searchresults.html?"
        f"ss={urllib.parse.quote(name)}"
        f"&checkin={check_in}&checkout={check_out}"
        f"&group_adults=1&no_rooms=1"
    )


def _days_between(d1: str, d2: str) -> int:
    from datetime import datetime
    try:
        return max(1, (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days)
    except Exception:
        return 1
