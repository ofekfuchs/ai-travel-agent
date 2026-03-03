"""Two-level caching: in-memory (fast) + Supabase (persistent).

Flow:
  cache_get(key):
    1. Check in-memory dict → instant
    2. Check Supabase cache table → ~100ms
    3. Return None if both miss

  cache_set(key, value):
    1. Write to in-memory dict
    2. Write to Supabase (async-safe, fire-and-forget on failure)

If Supabase is not configured or the table doesn't exist, falls back
silently to in-memory only. Nothing breaks.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

import httpx

from app.config import SUPABASE_URL, SUPABASE_ANON_KEY

_local_cache: dict[str, str] = {}
_supabase_available: bool | None = None


def _supabase_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _check_supabase() -> bool:
    """Lazy check: can we reach the Supabase cache table?"""
    global _supabase_available
    if _supabase_available is not None:
        return _supabase_available

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        _supabase_available = False
        return False

    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/cache?limit=1",
            headers=_supabase_headers(),
            timeout=5,
        )
        _supabase_available = resp.status_code == 200
    except Exception:
        _supabase_available = False

    return _supabase_available


def make_cache_key(prefix: str, params: dict) -> str:
    """Deterministic key from a namespace prefix + arbitrary parameters."""
    raw = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


def cache_get(key: str) -> Optional[dict]:
    """Return cached dict or None. Checks memory first, then Supabase."""
    raw = _local_cache.get(key)
    if raw is not None:
        return json.loads(raw)

    if not _check_supabase():
        return None

    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/cache",
            headers=_supabase_headers(),
            params={"key": f"eq.{key}", "select": "value"},
            timeout=5,
        )
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                value = rows[0]["value"]
                _local_cache[key] = json.dumps(value, default=str)
                return value
    except Exception:
        pass

    return None


def cache_set(key: str, value: dict) -> None:
    """Store in memory + Supabase. Never raises."""
    _local_cache[key] = json.dumps(value, default=str)

    if not _check_supabase():
        return

    try:
        httpx.post(
            f"{SUPABASE_URL}/rest/v1/cache",
            headers={
                **_supabase_headers(),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json={"key": key, "value": value},
            timeout=5,
        )
    except Exception:
        pass
