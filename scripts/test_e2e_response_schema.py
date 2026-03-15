#!/usr/bin/env python3
"""E2E tests focused on the /api/execute public response schema.

This script validates that the JSON returned by the running API server
conforms to the minimal public schema defined by ExecuteResponsePublic:

  - status: "ok" or "error"
  - error: null or a human-readable string
  - response: string or null
  - steps: array of Step objects (module/prompt/response)

Usage:
  python scripts/test_e2e_response_schema.py
  python scripts/test_e2e_response_schema.py --base-url http://localhost:8001
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from pydantic import ValidationError

from app.models.schemas import ExecuteResponsePublic

DEFAULT_BASE_URL = "http://localhost:8000"
TIMEOUT = 300


def call_api(base_url: str, prompt: str) -> dict:
    """Send a prompt to /api/execute and return the raw JSON dict."""
    payload = {"prompt": prompt}
    resp = httpx.post(
        f"{base_url}/api/execute",
        json=payload,
        timeout=TIMEOUT,
    )
    return resp.json()


def validate_public_schema(data: dict) -> tuple[bool, str]:
    """Validate the response against ExecuteResponsePublic.

    Returns (ok, message). If not ok, message contains the validation errors.
    """
    try:
        _ = ExecuteResponsePublic(
            status=data.get("status"),
            error=data.get("error"),
            response=data.get("response"),
            steps=data.get("steps") or [],
        )
        return True, "valid ExecuteResponsePublic"
    except ValidationError as e:
        return False, str(e)


def test_basic_prompt_schema(base_url: str) -> bool:
    """Test that a simple request returns a schema-valid response."""
    print("\n" + "=" * 70)
    print("  RESPONSE SCHEMA TEST: basic prompt")
    print("=" * 70)

    data = call_api(base_url, "Beach vacation in June from New York")

    ok, msg = validate_public_schema(data)
    print(f"  Schema validation: {'OK' if ok else 'FAIL'}")
    if not ok:
        print("  Validation error:")
        print(msg)
        # Show a small preview of the raw response for debugging
        preview = str(data)[:400]
        print(f"\n  Raw response preview:\n  {preview}")
        return False

    print("  Response matches ExecuteResponsePublic")
    print("\n  TEST: PASS")
    return True


def test_error_path_schema(base_url: str) -> bool:
    """Test that an invalid/empty prompt returns a schema-valid error response."""
    print("\n" + "=" * 70)
    print("  RESPONSE SCHEMA TEST: invalid/empty prompt")
    print("=" * 70)

    data = call_api(base_url, "   ")

    ok, msg = validate_public_schema(data)
    print(f"  Schema validation: {'OK' if ok else 'FAIL'}")
    if not ok:
        print("  Validation error:")
        print(msg)
        preview = str(data)[:400]
        print(f"\n  Raw response preview:\n  {preview}")
        return False

    status = data.get("status")
    error = data.get("error")
    print(f"  status={status!r}, error={error!r}")
    print("  (Expected: status='error' and a human-readable error message)")

    print("\n  TEST: PASS")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E tests for /api/execute public response schema")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    args = parser.parse_args()

    print("=" * 70)
    print("  /api/execute PUBLIC RESPONSE SCHEMA TESTS")
    print(f"  Server: {args.base_url}")
    print(f"  Timeout: {TIMEOUT}s per request")
    print("=" * 70)

    # Verify server is reachable
    try:
        httpx.get(f"{args.base_url}/api/team_info", timeout=5)
    except httpx.ConnectError:
        print(f"\n  ERROR: Cannot connect to {args.base_url}")
        print("  Is the server running? Start it with:")
        print("    python -m uvicorn app.main:app --port 8000")
        sys.exit(1)

    results: dict[str, bool] = {}

    try:
        results["basic_prompt"] = test_basic_prompt_schema(args.base_url)
    except Exception as e:
        print(f"\n  EXCEPTION in basic_prompt test: {e}")
        results["basic_prompt"] = False

    try:
        results["error_prompt"] = test_error_path_schema(args.base_url)
    except Exception as e:
        print(f"\n  EXCEPTION in error_prompt test: {e}")
        results["error_prompt"] = False

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    for name, passed in results.items():
        icon = "+" if passed else "X"
        print(f"  [{icon}] {name} — {'PASS' if passed else 'FAIL'}")

    failed = sum(1 for p in results.values() if not p)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

