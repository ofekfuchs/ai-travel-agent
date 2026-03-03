"""POI / Activities tool -- fetch points of interest from OpenTripMap.

Handles both plain-list and GeoJSON FeatureCollection response formats.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import OPENTRIPMAP_API_KEY
from app.models.shared_state import SharedState
from app.utils.cache import cache_get, cache_set, make_cache_key
from app.utils.step_logger import log_tool_call

_BASE = "https://api.opentripmap.com/0.1/en/places"


def search_pois(
    state: SharedState,
    latitude: float,
    longitude: float,
    radius_m: int = 5000,
    kinds: str = "interesting_places",
    limit: int = 15,
    destination_name: str = "",
) -> list[dict[str, Any]]:
    """Search for POIs near a coordinate and store results in Shared State."""
    params = {
        "lat": latitude,
        "lon": longitude,
        "radius": radius_m,
        "kinds": kinds,
        "destination": destination_name,
    }

    ck = make_cache_key("poi", params)
    cached = cache_get(ck)
    if cached is not None:
        state.poi_list.extend(cached.get("pois", []))
        log_tool_call(state, "Executor", "poi_search", params,
                      {"source": "cache", "count": len(cached.get("pois", []))})
        return cached.get("pois", [])

    if not OPENTRIPMAP_API_KEY:
        log_tool_call(state, "Executor", "poi_search", params,
                      {"error": "OPENTRIPMAP_API_KEY not configured"})
        return []

    try:
        resp = httpx.get(
            f"{_BASE}/radius",
            params={
                "radius": radius_m,
                "lon": longitude,
                "lat": latitude,
                "kinds": kinds,
                "limit": limit,
                "format": "json",
                "apikey": OPENTRIPMAP_API_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()

        raw_list = _normalize_response(raw, limit)
        pois = _enrich_pois(raw_list)
        state.poi_list.extend(pois)
        cache_set(ck, {"pois": pois})

        log_tool_call(state, "Executor", "poi_search", params, {"count": len(pois)})
        return pois

    except Exception as exc:
        log_tool_call(state, "Executor", "poi_search", params, {"error": str(exc)})
        return []


def _normalize_response(raw: Any, limit: int) -> list[dict]:
    """Handle both plain list and GeoJSON FeatureCollection formats."""
    if isinstance(raw, list):
        return raw[:limit]

    if isinstance(raw, dict) and raw.get("type") == "FeatureCollection":
        items = []
        for feature in raw.get("features", [])[:limit]:
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [0, 0])
            items.append({
                "name": props.get("name", "Unnamed"),
                "kinds": props.get("kinds", ""),
                "xid": props.get("xid", ""),
                "point": {"lon": coords[0], "lat": coords[1]} if len(coords) >= 2 else {},
            })
        return items

    return []


def _enrich_pois(items: list[dict]) -> list[dict[str, Any]]:
    """Extract a clean list of POI dicts from the raw API response."""
    pois: list[dict[str, Any]] = []
    for item in items:
        name = item.get("name", "Unnamed")
        if not name or name == "Unnamed":
            continue
        pois.append(
            {
                "name": name,
                "kinds": item.get("kinds", ""),
                "lat": item.get("point", {}).get("lat", 0),
                "lon": item.get("point", {}).get("lon", 0),
                "xid": item.get("xid", ""),
            }
        )
    return pois
