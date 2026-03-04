"""Dynamic geocoding via OpenStreetMap Nominatim API.

Free, no API key required, works for any city worldwide.
Results are cached in-memory for the process lifetime.
"""

from __future__ import annotations

import httpx

_cache: dict[str, tuple[float, float] | None] = {}


def geocode(city_name: str) -> tuple[float, float] | None:
    """Resolve a city name to (latitude, longitude).

    Returns None if the city cannot be found.
    """
    key = city_name.strip().lower()
    if key in _cache:
        return _cache[key]

    try:
        resp = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": city_name, "format": "json", "limit": 1},
            headers={"User-Agent": "ai-travel-agent/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            coords = (float(results[0]["lat"]), float(results[0]["lon"]))
            _cache[key] = coords
            return coords
    except Exception:
        pass

    _cache[key] = None
    return None
