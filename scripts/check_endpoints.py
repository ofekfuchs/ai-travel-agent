#!/usr/bin/env python3
"""Validate all API endpoints and response shapes.

Calls GET /health, GET /api/team_info, GET /api/agent_info,
GET /api/model_architecture, GET / (frontend), and POST /api/execute.
Verifies each response has the required keys and types; for /api/execute
checks status, error, response, steps and that each step has module, prompt, response.

Usage:
  python scripts/check_endpoints.py
  python scripts/check_endpoints.py --base-url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

DEFAULT_BASE = "http://127.0.0.1:8000"
TIMEOUT = 10


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate API endpoints and response shapes")
    ap.add_argument("--base-url", default=DEFAULT_BASE, help="Base URL of the running server")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    errors: list[str] = []
    results: list[tuple[str, bool, str]] = []

    def ok(name: str, msg: str) -> None:
        results.append((name, True, msg))
        print(f"  [OK] {name}: {msg}")

    def fail(name: str, msg: str) -> None:
        results.append((name, False, msg))
        errors.append(f"{name}: {msg}")
        print(f"  [FAIL] {name}: {msg}")

    print(f"Base URL: {base}\n")

    # ── GET /health ─────────────────────────────────────────────────────
    print("GET /health")
    try:
        r = httpx.get(f"{base}/health", timeout=TIMEOUT)
        if r.status_code != 200:
            fail("/health", f"status {r.status_code}")
        else:
            data = r.json()
            if data.get("status") == "ok":
                ok("/health", "status=ok")
            else:
                fail("/health", f"unexpected body: {data}")
    except Exception as e:
        fail("/health", str(e))
    print()

    # ── GET /api/team_info (Course: group_batch_order_number, team_name, students) ──
    print("GET /api/team_info")
    try:
        r = httpx.get(f"{base}/api/team_info", timeout=TIMEOUT)
        if r.status_code != 200:
            fail("/api/team_info", f"status {r.status_code}")
        else:
            data = r.json()
            need = {"group_batch_order_number", "team_name", "students"}
            missing = need - set(data.keys())
            if missing:
                fail("/api/team_info", f"missing keys: {missing}")
            elif not isinstance(data.get("students"), list):
                fail("/api/team_info", "students must be an array")
            else:
                for i, s in enumerate(data["students"]):
                    if not isinstance(s, dict) or not ("name" in s and "email" in s):
                        fail("/api/team_info", f"students[{i}] must have name and email")
                        break
                else:
                    ok("/api/team_info", f"group={data['group_batch_order_number']!r}, team={data['team_name']!r}, students={len(data['students'])}")
    except Exception as e:
        fail("/api/team_info", str(e))
    print()

    # ── GET /api/agent_info (Course: description, purpose, prompt_template, prompt_examples) ──
    print("GET /api/agent_info")
    try:
        r = httpx.get(f"{base}/api/agent_info", timeout=TIMEOUT)
        if r.status_code != 200:
            fail("/api/agent_info", f"status {r.status_code}")
        else:
            data = r.json()
            need = {"description", "purpose", "prompt_template", "prompt_examples"}
            missing = need - set(data.keys())
            if missing:
                fail("/api/agent_info", f"missing keys: {missing}")
            elif not isinstance(data.get("prompt_template"), dict) or "template" not in (data.get("prompt_template") or {}):
                fail("/api/agent_info", "prompt_template must be an object with 'template'")
            elif not isinstance(data.get("prompt_examples"), list):
                fail("/api/agent_info", "prompt_examples must be an array")
            else:
                for i, ex in enumerate(data["prompt_examples"]):
                    if not isinstance(ex, dict):
                        fail("/api/agent_info", f"prompt_examples[{i}] must be an object")
                        break
                    need_ex = {"prompt", "full_response", "steps"}
                    miss_ex = need_ex - set(ex.keys())
                    if miss_ex:
                        fail("/api/agent_info", f"prompt_examples[{i}] missing: {miss_ex}")
                        break
                    if not isinstance(ex.get("steps"), list):
                        fail("/api/agent_info", f"prompt_examples[{i}].steps must be an array")
                        break
                else:
                    ok("/api/agent_info", f"description, purpose, prompt_template, prompt_examples ({len(data['prompt_examples'])} item(s), each with prompt + full_response + steps)")
    except Exception as e:
        fail("/api/agent_info", str(e))
    print()

    # ── GET /api/model_architecture (Course: image/png, body = PNG) ──
    print("GET /api/model_architecture")
    try:
        r = httpx.get(f"{base}/api/model_architecture", timeout=TIMEOUT)
        if r.status_code != 200:
            fail("/api/model_architecture", f"status {r.status_code}")
        else:
            ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if ct != "image/png":
                fail("/api/model_architecture", f"Content-Type must be image/png, got {ct!r}")
            elif len(r.content) < 100:
                fail("/api/model_architecture", f"body too small ({len(r.content)} bytes)")
            elif not r.content.startswith(b"\x89PNG"):
                fail("/api/model_architecture", "body does not look like PNG (missing PNG signature)")
            else:
                ok("/api/model_architecture", f"image/png, {len(r.content)} bytes")
    except Exception as e:
        fail("/api/model_architecture", str(e))
    print()

    # ── GET / (frontend) ───────────────────────────────────────────────
    print("GET / (frontend)")
    try:
        r = httpx.get(f"{base}/", timeout=TIMEOUT)
        if r.status_code != 200:
            fail("GET /", f"status {r.status_code}")
        else:
            text = r.text or ""
            if "AI Travel" in text or "travel" in text.lower() or len(text) > 100:
                ok("GET /", f"HTML length {len(text)}")
            else:
                fail("GET /", "response too short or unrecognized")
    except Exception as e:
        fail("GET /", str(e))
    print()

    # ── POST /api/execute (response shape: status, error, response, steps) ──
    print("POST /api/execute (shape check)")
    try:
        # Use off-topic prompt so agent returns quickly (scope guard)
        r = httpx.post(
            f"{base}/api/execute",
            json={"prompt": "What is the capital of France?"},
            timeout=60,
        )
        if r.status_code != 200:
            fail("POST /api/execute", f"status {r.status_code}")
        else:
            data = r.json()
            need = {"status", "error", "response", "steps"}
            missing = need - set(data.keys())
            if missing:
                fail("POST /api/execute", f"missing keys: {missing}")
            elif data["status"] not in ("ok", "error"):
                fail("POST /api/execute", f"status must be 'ok' or 'error', got {data['status']!r}")
            elif not isinstance(data["steps"], list):
                fail("POST /api/execute", "steps must be an array")
            else:
                for i, step in enumerate(data["steps"]):
                    if not isinstance(step, dict):
                        fail("POST /api/execute", f"steps[{i}] must be an object")
                        break
                    need_step = {"module", "prompt", "response"}
                    miss_step = need_step - set(step.keys())
                    if miss_step:
                        fail("POST /api/execute", f"steps[{i}] missing: {miss_step}")
                        break
                else:
                    ok("POST /api/execute", f"status={data['status']!r}, steps={len(data['steps'])}")
    except Exception as e:
        fail("POST /api/execute", str(e))
    print()

    # ── Summary ─────────────────────────────────────────────────────────
    print("=" * 60)
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    print(f"Result: {passed}/{total} endpoints passed")
    if errors:
        print("\nIssues:")
        for e in errors:
            print(f"  - {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
