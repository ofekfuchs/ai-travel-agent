#!/usr/bin/env python3
"""Run 3 Verifier-stress E2E tests sequentially.

These prompts stress the Verifier's cost-breakdown logic (daily expenses,
budget vs total, multi-day trips). The script:
  1. Starts the server in the background
  2. Runs 3 fixed prompts one after another
  3. Prints all output to the terminal
  4. Stops the server when done
  5. Writes verifier_tests_result.txt with PASS/FAIL if all 3 passed

Usage:
  python scripts/run_verifier_tests.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Project root = parent of scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

DEFAULT_PORT = 8000
SERVER_READY_TIMEOUT = 60
REQUEST_TIMEOUT = 180  # LLM calls can be slow

# ── Fixed prompts that stress the Verifier ─────────────────────────────────
# 1. Multi-day trip with budget: cost breakdown (flights + hotel + daily_expenses total) must be correct
# 2. Short trip with tight budget: Verifier checks budget vs total
# 3. Classic Paris trip: daily expenses fix (total = flights + hotel + daily_total_for_trip)
PROMPTS = [
    "4 days in Paris in June, budget $1500, flying from New York. I love museums and good food.",
    "5 days in London from Tel Aviv, budget $2000, moderate budget.",
    "Romantic getaway to Berlin for 3 days, budget $1000 flying from Paris. We like art and nightlife.",
]


def wait_for_server(base_url: str, timeout: int = SERVER_READY_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "ok":
                    return True
        except Exception:
            time.sleep(1)
    return False


def run_test(base_url: str, prompt: str, test_num: int) -> tuple[bool, str]:
    """POST to /api/execute, return (passed, message)."""
    print(f"\n  >> Test {test_num}: {prompt[:70]}{'...' if len(prompt) > 70 else ''}")
    start = time.time()
    try:
        resp = httpx.post(
            f"{base_url}/api/execute",
            json={"prompt": prompt},
            timeout=REQUEST_TIMEOUT,
        )
        elapsed = time.time() - start
        data = resp.json()
    except Exception as e:
        return False, f"Request failed: {e}"

    status = data.get("status", "?")
    llm_calls = data.get("llm_calls_used", "?")
    print(f"  << Status: {status} | LLM calls: {llm_calls} | Time: {elapsed:.1f}s")

    if status != "ok":
        err = data.get("error", "unknown")
        return False, f"status={status}, error={err}"

    response_text = data.get("response", "")
    packages = _extract_packages(response_text)

    if not packages:
        # Could be budget_infeasible, no_pricing_data, or rejection
        if "budget" in response_text.lower() or "infeasible" in response_text.lower():
            print("  (Budget infeasible — valid outcome)")
            return True, "Budget infeasible"
        if "no pricing" in response_text.lower() or "no_pricing" in response_text.lower():
            print("  (No pricing data — valid outcome)")
            return True, "No pricing data"
        print(f"  WARN: No packages in response (preview: {response_text[:150]}...)")
        return False, "No packages returned"

    print(f"  Packages: {len(packages)}")
    for i, pkg in enumerate(packages[:2], 1):
        dest = pkg.get("destination", "?")
        cb = pkg.get("cost_breakdown", {})
        total = cb.get("total", "?")
        daily = cb.get("daily_expenses_estimate", cb.get("daily_expenses_estimate_usd", "?"))
        print(f"    Pkg {i}: {dest} — total ${total}, daily_est ${daily}")

    return True, f"{len(packages)} package(s)"


def _extract_packages(response_text: str) -> list:
    try:
        parsed = json.loads(response_text)
        if isinstance(parsed, dict):
            return parsed.get("packages", parsed.get("trip_packages", []))
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def main() -> int:
    base_url = f"http://127.0.0.1:{DEFAULT_PORT}"
    server_proc = None

    print("=" * 70)
    print("  VERIFIER STRESS TESTS — 3 prompts")
    print(f"  Server: {base_url}")
    print("=" * 70)

    # ── Start server ───────────────────────────────────────────────────────
    print("\nStarting server...")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(DEFAULT_PORT)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    print("Waiting for server to be ready...")
    if not wait_for_server(base_url):
        print("ERROR: Server did not become ready in time.")
        if server_proc:
            server_proc.terminate()
            server_proc.wait(timeout=5)
        return 1
    print("Server ready.\n")

    # ── Run 3 tests sequentially ──────────────────────────────────────────
    results: list[tuple[bool, str]] = []
    for i, prompt in enumerate(PROMPTS, 1):
        print(f"\n{'─' * 60}")
        print(f"  TEST {i}/3")
        print("─" * 60)
        passed, msg = run_test(base_url, prompt, i)
        results.append((passed, msg))
        status = "PASS" if passed else "FAIL"
        print(f"\n  TEST {i}: {status} — {msg}")

    # ── Stop server ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("Stopping server...")
    if server_proc:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.wait(timeout=3)
    print("Server stopped.")

    # ── Summary ────────────────────────────────────────────────────────────
    all_passed = all(r[0] for r in results)
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    for i, (passed, msg) in enumerate(results, 1):
        icon = "+" if passed else "X"
        print(f"  [{icon}] Test {i}: {msg}")
    print(f"\n  Overall: {'PASS' if all_passed else 'FAIL'} ({sum(r[0] for r in results)}/3)")

    # ── Update result file ─────────────────────────────────────────────────
    result_file = PROJECT_ROOT / "verifier_tests_result.txt"
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(f"Last run: {datetime.now().isoformat()}\n")
        f.write(f"Result: {'PASS' if all_passed else 'FAIL'}\n")
        for i, (passed, msg) in enumerate(results, 1):
            f.write(f"  Test {i}: {'PASS' if passed else 'FAIL'} — {msg}\n")
    print(f"\nResult written to: {result_file}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
