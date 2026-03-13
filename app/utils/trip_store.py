"""Persist trip data and execution traces to Supabase.

Tables used (all fail gracefully if table doesn't exist):

  trips:
    id, created_at, session_id, prompt, constraints, packages,
    llm_calls_used, status

  sessions:
    id, created_at, session_id, prompt, state_snapshot

  execution_logs:
    id, created_at, session_id, round_num, action, reason, data_snapshot
"""

from __future__ import annotations

import json
from typing import Optional

import httpx

from app.config import SUPABASE_URL, SUPABASE_ANON_KEY

_supabase_warned = False
_table_warnings: set[str] = set()


def _headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _safe_post(table: str, row: dict) -> bool:
    global _supabase_warned
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        if not _supabase_warned:
            print("[Supabase] Not configured — using in-memory fallback. "
                  "Set SUPABASE_URL and SUPABASE_ANON_KEY to enable persistence.", flush=True)
            _supabase_warned = True
        return False
    try:
        resp = httpx.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=_headers(),
            json=row,
            timeout=5,
        )
        if resp.status_code not in (200, 201):
            if table not in _table_warnings:
                print(f"[Supabase] Write to '{table}' failed: HTTP {resp.status_code} "
                      f"(further errors for this table will be suppressed)", flush=True)
                _table_warnings.add(table)
            return False
        return True
    except Exception as exc:
        if table not in _table_warnings:
            print(f"[Supabase] Write to '{table}' error: {exc}", flush=True)
            _table_warnings.add(table)
        return False


def save_trip(
    prompt: str,
    constraints: Optional[dict],
    packages: list[dict],
    llm_calls_used: int,
    status: str = "approved",
    session_id: str = "",
) -> bool:
    """Save a completed trip to the trips table."""
    row = {
        "prompt": prompt,
        "session_id": session_id,
        "constraints": json.loads(json.dumps(constraints or {}, default=str)),
        "packages": json.loads(json.dumps(packages, default=str)),
        "llm_calls_used": llm_calls_used,
        "status": status,
    }
    return _safe_post("trips", row)


def save_session(session_id: str, prompt: str, state_snapshot: dict) -> bool:
    """Persist session state so users can follow up on plans."""
    row = {
        "session_id": session_id,
        "prompt": prompt,
        "state_snapshot": json.loads(json.dumps(state_snapshot, default=str)),
    }
    return _safe_post("sessions", row)


def log_execution(
    session_id: str,
    round_num: int,
    action: str,
    reason: str,
    data_snapshot: dict,
) -> bool:
    """Log a Supervisor decision + data snapshot for audit trail."""
    row = {
        "session_id": session_id,
        "round_num": round_num,
        "action": action,
        "reason": reason,
        "data_snapshot": json.loads(json.dumps(data_snapshot, default=str)),
    }
    return _safe_post("execution_logs", row)
