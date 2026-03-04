"""Weather tool -- fetch weather context from Open-Meteo (completely free, no API key).

For near-term trips (within 16 days): returns a real forecast.
For far-term trips: returns historical climate averages for the same calendar
period in recent years so the agent can say "May in Lisbon is typically 18-24 C".

Auto-geocodes city names when lat/lon are missing or zero.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.models.shared_state import SharedState
from app.tools.geocode import geocode
from app.utils.cache import cache_get, cache_set, make_cache_key
from app.utils.step_logger import log_tool_call


def get_weather(
    state: SharedState,
    latitude: float = 0.0,
    longitude: float = 0.0,
    start_date: str = "",
    end_date: str = "",
    destination_name: str = "",
) -> dict[str, Any]:
    """Fetch weather context for a location and date range.

    If latitude/longitude are 0 or missing, auto-geocodes from destination_name.
    Automatically picks between the forecast API (near-term) and the
    historical-weather API (far-term climate normals).
    """
    if (not latitude or not longitude) and destination_name:
        coords = geocode(destination_name)
        if coords:
            latitude, longitude = coords

    if not latitude or not longitude:
        log_tool_call(state, "Executor", "weather_lookup",
                      {"destination": destination_name}, {"error": "Could not resolve coordinates"})
        return {"error": "Could not resolve coordinates", "destination": destination_name}

    params = {
        "lat": latitude,
        "lon": longitude,
        "start": start_date,
        "end": end_date,
        "destination": destination_name,
    }

    ck = make_cache_key("weather", params)
    cached = cache_get(ck)
    if cached is not None:
        state.weather_context.append(cached)
        log_tool_call(state, "Executor", "weather_lookup", params, {"source": "cache"})
        return cached

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        days_ahead = (start - date.today()).days

        if days_ahead <= 16:
            result = _forecast(latitude, longitude, start_date, end_date, destination_name)
        else:
            result = _climate_normals(latitude, longitude, start_date, end_date, destination_name)

        state.weather_context.append(result)
        cache_set(ck, result)
        log_tool_call(state, "Executor", "weather_lookup", params, {"type": result.get("type", "unknown")})
        return result

    except Exception as exc:
        error_result: dict[str, Any] = {"error": str(exc), "destination": destination_name}
        log_tool_call(state, "Executor", "weather_lookup", params, {"error": str(exc)})
        return error_result


def _forecast(lat: float, lon: float, start: str, end: str, name: str) -> dict[str, Any]:
    """Open-Meteo 16-day forecast API."""
    resp = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            "start_date": start,
            "end_date": end,
            "timezone": "auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    daily = data.get("daily", {})
    return {
        "type": "forecast",
        "destination": name,
        "start": start,
        "end": end,
        "daily_max_temp": daily.get("temperature_2m_max", []),
        "daily_min_temp": daily.get("temperature_2m_min", []),
        "daily_precip_mm": daily.get("precipitation_sum", []),
        "dates": daily.get("time", []),
    }


def _climate_normals(lat: float, lon: float, start: str, end: str, name: str) -> dict[str, Any]:
    """Approximate climate by averaging the same calendar window over the
    last 3 years using the Open-Meteo historical-weather API."""
    start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end, "%Y-%m-%d").date()

    all_max: list[float] = []
    all_min: list[float] = []

    for years_back in range(1, 4):
        hist_start = start_dt.replace(year=start_dt.year - years_back)
        hist_end = end_dt.replace(year=end_dt.year - years_back)
        try:
            resp = httpx.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "start_date": hist_start.isoformat(),
                    "end_date": hist_end.isoformat(),
                    "timezone": "auto",
                },
                timeout=10,
            )
            resp.raise_for_status()
            daily = resp.json().get("daily", {})
            all_max.extend(daily.get("temperature_2m_max", []))
            all_min.extend(daily.get("temperature_2m_min", []))
        except Exception:
            continue

    avg_max = round(sum(all_max) / len(all_max), 1) if all_max else 0
    avg_min = round(sum(all_min) / len(all_min), 1) if all_min else 0

    return {
        "type": "climate_normals",
        "destination": name,
        "start": start,
        "end": end,
        "avg_high_c": avg_max,
        "avg_low_c": avg_min,
        "note": f"Based on historical data ({start_dt.year - 3}-{start_dt.year - 1})",
    }
