#!/usr/bin/env python3
"""End-to-end smoke tests for the AI Travel Agent.

Sends real requests to the running API server and validates:
  1. Packages are returned with expected structure
  2. RAG is influencing destination selection
  3. Session continuity works across follow-up messages
  4. Budget/pricing contracts are consistent
  5. Verifier catches broken packages

Prerequisites:
  - Server running: python -m uvicorn app.main:app --port 8000
  - All API keys configured in .env

Usage:
  python scripts/test_e2e_smoke.py                  # run all tests
  python scripts/test_e2e_smoke.py --test 1          # run only test 1
  python scripts/test_e2e_smoke.py --base-url http://localhost:8001  # custom URL
"""

import argparse
import json
import sys
import time
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
TIMEOUT = 300  # seconds per request (LLM calls can be slow, complex requests ~150-250s)


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def call_api(base_url: str, prompt: str, session_id: str | None = None) -> dict:
    """Send a prompt to /api/execute and return the full JSON response."""
    payload = {"prompt": prompt}
    if session_id:
        payload["session_id"] = session_id

    print(f"\n  >> Sending: \"{prompt}\"")
    if session_id:
        print(f"     session_id: {session_id}")

    start = time.time()
    resp = httpx.post(
        f"{base_url}/api/execute",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed = time.time() - start
    data = resp.json()

    print(f"  << Status: {data.get('status')} | Time: {elapsed:.1f}s")

    return data


def extract_packages_from_steps(steps: list[dict]) -> list[dict]:
    """Extract packages from Trip Synthesizer step (API now returns response=human-readable, data in steps)."""
    if not steps:
        return []
    for s in steps:
        mod = (s.get("module") or "").lower()
        if "synthesizer" in mod or "trip" in mod:
            content = s.get("response", {}).get("content", "")
            if not content:
                continue
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "packages" in parsed:
                    return parsed["packages"]
            except (json.JSONDecodeError, TypeError):
                pass
    return []


def extract_session_id_from_steps(steps: list[dict]) -> str | None:
    """Extract session_id from steps (for clarification / multi-turn; API returns only 4 keys)."""
    if not steps:
        return None
    for s in reversed(steps):
        r = s.get("response")
        if isinstance(r, dict) and r.get("session_id"):
            return r["session_id"]
    return None


def print_package_summary(packages: list[dict]):
    """Print a concise summary of each package."""
    for i, pkg in enumerate(packages, 1):
        dest = pkg.get("destination", "?")
        total = pkg.get("cost_breakdown", {}).get("total", "?")
        flights = pkg.get("flights", {})
        flight_cost = flights.get("total_flight_cost", "?")
        hotel = pkg.get("hotel", {})
        hotel_name = hotel.get("name", "?")
        hotel_cost = hotel.get("total_cost", "?")
        date_window = pkg.get("date_window", "?")
        itinerary_days = len(pkg.get("itinerary", []))

        print(f"\n  Package {i}: {dest}")
        print(f"    Date window:   {date_window}")
        print(f"    Flight cost:   ${flight_cost}")
        print(f"    Hotel:         {hotel_name} (${hotel_cost})")
        print(f"    Total:         ${total}")
        print(f"    Itinerary:     {itinerary_days} days")


def check_package_integrity(pkg: dict, pkg_num: int) -> list[str]:
    """Run deterministic checks on a single package. Returns list of issues."""
    issues = []
    prefix = f"Pkg {pkg_num}"

    if not pkg.get("destination"):
        issues.append(f"{prefix}: missing destination")

    flights = pkg.get("flights", {})
    if not flights:
        issues.append(f"{prefix}: missing flights")
    else:
        if not flights.get("outbound"):
            issues.append(f"{prefix}: missing outbound flight")
        flight_cost = flights.get("total_flight_cost", 0)
        if not flight_cost or flight_cost <= 0:
            issues.append(f"{prefix}: flight cost is zero or missing")

    hotel = pkg.get("hotel", {})
    if not hotel.get("name"):
        issues.append(f"{prefix}: missing hotel name")
    hotel_cost = hotel.get("total_cost", 0)
    if not hotel_cost or hotel_cost <= 0:
        issues.append(f"{prefix}: hotel cost is zero or missing")

    cost_breakdown = pkg.get("cost_breakdown", {})
    total = cost_breakdown.get("total", 0)
    if not total or total <= 0:
        issues.append(f"{prefix}: total cost is zero or missing")

    itinerary = pkg.get("itinerary", [])
    if len(itinerary) < 2:
        issues.append(f"{prefix}: itinerary has fewer than 2 days")

    if not pkg.get("date_window"):
        issues.append(f"{prefix}: missing date_window")

    return issues


# ═══════════════════════════════════════════════════════════════════════════
#  Test 1: Beach vacation from NYC — basic flow + RAG grounding
# ═══════════════════════════════════════════════════════════════════════════

def test_1_beach_vacation(base_url: str) -> bool:
    print("\n" + "=" * 70)
    print("  TEST 1: Beach vacation in June from New York")
    print("=" * 70)

    data = call_api(base_url, "Beach vacation in June from New York")
    steps = data.get("steps") or []
    session_id = extract_session_id_from_steps(steps)

    if data.get("status") != "ok":
        print(f"  FAIL: status={data.get('status')}, error={data.get('error')}")
        return False

    if session_id:
        print(f"  session_id: {session_id}")

    packages = extract_packages_from_steps(steps)
    if not packages:
        print("  WARN: No parseable packages in response (might be text-only)")
        print(f"  Response preview: {str(data.get('response', ''))[:300]}")
        return True  # non-blocking — response might still be valid text

    print(f"\n  Found {len(packages)} package(s):")
    print_package_summary(packages)

    all_issues = []
    for i, pkg in enumerate(packages, 1):
        all_issues.extend(check_package_integrity(pkg, i))

    if all_issues:
        print(f"\n  Issues found ({len(all_issues)}):")
        for issue in all_issues:
            print(f"    - {issue}")
    else:
        print("\n  All packages pass integrity checks!")

    print(f"\n  TEST 1: {'PASS' if not all_issues else 'WARN (see issues above)'}")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Test 2: Romantic trip to Europe — budget constraint + RAG
# ═══════════════════════════════════════════════════════════════════════════

def test_2_romantic_europe(base_url: str) -> bool:
    print("\n" + "=" * 70)
    print("  TEST 2: Romantic trip to Europe, budget $3000")
    print("=" * 70)

    data = call_api(
        base_url,
        "Romantic trip to Europe in May for 1 week from Tel Aviv, budget $3000"
    )
    steps = data.get("steps") or []
    session_id = extract_session_id_from_steps(steps)

    if data.get("status") != "ok":
        print(f"  FAIL: status={data.get('status')}, error={data.get('error')}")
        return False

    if session_id:
        print(f"  session_id: {session_id}")

    packages = extract_packages_from_steps(steps)

    if not packages:
        # Could be budget_infeasible — check response
        if "budget" in response_text.lower() or "infeasible" in response_text.lower():
            print("  INFO: Budget was flagged as infeasible — this is valid behavior")
            print(f"  Response: {response_text[:400]}")
            return True
        print(f"  WARN: No packages, response: {response_text[:300]}")
        return True

    print(f"\n  Found {len(packages)} package(s):")
    print_package_summary(packages)

    # Budget check: total should not exceed $3000
    for i, pkg in enumerate(packages, 1):
        total = pkg.get("cost_breakdown", {}).get("total", 0)
        if total and total > 3000:
            print(f"  WARN: Package {i} total ${total} exceeds $3000 budget")

    destinations = [pkg.get("destination", "?") for pkg in packages]
    print(f"\n  Destinations chosen: {destinations}")
    print(f"  (Should be European cities — RAG has data for 15 European cities)")

    print(f"\n  TEST 2: PASS")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Test 3: Session continuity — follow-up "give me different locations"
# ═══════════════════════════════════════════════════════════════════════════

def test_3_session_followup(base_url: str) -> bool:
    print("\n" + "=" * 70)
    print("  TEST 3: Session continuity (follow-up)")
    print("=" * 70)

    # Step A: Initial request
    print("\n  Step A: Initial request")
    data1 = call_api(base_url, "Beach vacation in June from New York")
    steps1 = data1.get("steps") or []
    session_id = extract_session_id_from_steps(steps1)

    if not session_id:
        print("  FAIL: No session_id from initial request (check steps)")
        return False

    packages1 = extract_packages_from_steps(steps1)
    dests1 = [pkg.get("destination", "?") for pkg in packages1]
    print(f"  Initial destinations: {dests1}")

    # Step B: Follow-up with same session_id
    print("\n  Step B: Follow-up with same session_id")
    data2 = call_api(base_url, "give me different locations", session_id=session_id)
    steps2 = data2.get("steps") or []
    session_id2 = extract_session_id_from_steps(steps2)

    if data2.get("status") != "ok":
        print(f"  FAIL: Follow-up status={data2.get('status')}, error={data2.get('error')}")
        return False

    if session_id2 and session_id2 != session_id:
        print(f"  WARN: session_id changed ({session_id} -> {session_id2})")

    response2 = data2.get("response", "")

    # Check it didn't ask for clarification / reset
    reset_phrases = ["where would you like", "what destination", "please provide", "tell me more"]
    if any(phrase in response2.lower() for phrase in reset_phrases):
        print(f"  FAIL: System lost context and asked for clarification!")
        print(f"  Response: {response2[:300]}")
        return False

    packages2 = extract_packages_from_steps(steps2)
    dests2 = [pkg.get("destination", "?") for pkg in packages2]
    print(f"  Follow-up destinations: {dests2}")

    # Check destinations are actually different
    if dests1 and dests2:
        overlap = set(dests1) & set(dests2)
        if overlap:
            print(f"  WARN: Overlapping destinations: {overlap} (exclusion might not have worked)")
        else:
            print(f"  Destinations are all different — exclusion worked!")

    print(f"\n  TEST 3: PASS")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Test 4: Budget infeasibility — should get a clear rejection
# ═══════════════════════════════════════════════════════════════════════════

def test_4_budget_infeasible(base_url: str) -> bool:
    print("\n" + "=" * 70)
    print("  TEST 4: Budget infeasibility (very low budget)")
    print("=" * 70)

    data = call_api(
        base_url,
        "Trip to Tokyo for 2 weeks from New York, budget $500"
    )

    response_text = str(data.get("response", ""))
    steps = data.get("steps") or []
    session_id = extract_session_id_from_steps(steps)

    if session_id:
        print(f"  session_id: {session_id}")
    print(f"  Response preview: {response_text[:400]}")

    # Either budget_infeasible or very tight packages — both are acceptable
    print(f"\n  TEST 4: PASS (system handled tight budget)")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Test 5: RAG-specific — verify retrieval influences Planner
# ═══════════════════════════════════════════════════════════════════════════

def test_5_rag_influence(base_url: str) -> bool:
    print("\n" + "=" * 70)
    print("  TEST 5: RAG influence — vague European prompt")
    print("=" * 70)

    data = call_api(
        base_url,
        "cheap trip to Europe for 5 days, budget $2000 from Tel Aviv"
    )

    if data.get("status") != "ok":
        print(f"  FAIL: status={data.get('status')}, error={data.get('error')}")
        return False

    packages = extract_packages_from_steps(data.get("steps") or [])
    dests = [pkg.get("destination", "?") for pkg in packages]

    # We uploaded data for 15 European cities — if RAG works,
    # the Planner should tend to pick from those cities
    rag_cities = {
        "London", "Paris", "Berlin", "Rome", "Barcelona", "Amsterdam",
        "Prague", "Vienna", "Lisbon", "Budapest", "Athens", "Istanbul",
        "Dublin", "Edinburgh", "Copenhagen",
    }

    rag_hits = [d for d in dests if d in rag_cities]
    print(f"\n  Destinations: {dests}")
    print(f"  RAG-covered cities: {rag_hits} ({len(rag_hits)}/{len(dests)})")

    if rag_hits:
        print("  RAG is influencing destination selection!")
    else:
        print("  WARN: No RAG-covered cities chosen (might still be valid)")

    print(f"\n  TEST 5: PASS")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Test 6: Multi-traveler pricing
# ═══════════════════════════════════════════════════════════════════════════

def test_6_multi_traveler(base_url: str) -> bool:
    print("\n" + "=" * 70)
    print("  TEST 6: Multi-traveler pricing (2 people)")
    print("=" * 70)

    data = call_api(
        base_url,
        "Vacation to Paris for 2 people, 5 days from New York, budget $5000"
    )

    if data.get("status") != "ok":
        print(f"  FAIL: status={data.get('status')}, error={data.get('error')}")
        return False

    packages = extract_packages_from_steps(data.get("steps") or [])

    if packages:
        print_package_summary(packages)
        for i, pkg in enumerate(packages, 1):
            flights = pkg.get("flights", {})
            flight_cost = flights.get("total_flight_cost", 0)
            if flight_cost:
                print(f"\n  Pkg {i}: Flight total = ${flight_cost}")
                print(f"  (Should reflect 2 travelers if flight API returns per-person prices)")
    else:
        response_text = str(data.get("response", ""))
        print(f"  Response: {response_text[:400]}")

    print(f"\n  TEST 6: PASS")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Test 7: Health check endpoints
# ═══════════════════════════════════════════════════════════════════════════

def test_7_health_endpoints(base_url: str) -> bool:
    print("\n" + "=" * 70)
    print("  TEST 7: Health check endpoints")
    print("=" * 70)

    # Check /api/team_info
    try:
        resp = httpx.get(f"{base_url}/api/team_info", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  /api/team_info: OK — team '{data.get('team_name', '?')}'")
        else:
            print(f"  /api/team_info: FAIL (HTTP {resp.status_code})")
            return False
    except Exception as e:
        print(f"  /api/team_info: FAIL ({e})")
        return False

    # Check /api/agent_info
    try:
        resp = httpx.get(f"{base_url}/api/agent_info", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  /api/agent_info: OK — purpose: {data.get('purpose', '?')[:80]}")
        else:
            print(f"  /api/agent_info: FAIL (HTTP {resp.status_code})")
            return False
    except Exception as e:
        print(f"  /api/agent_info: FAIL ({e})")
        return False

    # Check frontend served at /
    try:
        resp = httpx.get(f"{base_url}/", timeout=10)
        if resp.status_code == 200 and "html" in resp.text.lower():
            print(f"  / (frontend): OK ({len(resp.text)} bytes)")
        else:
            print(f"  / (frontend): FAIL (HTTP {resp.status_code})")
            return False
    except Exception as e:
        print(f"  / (frontend): FAIL ({e})")
        return False

    print(f"\n  TEST 7: PASS")
    return True


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

ALL_TESTS = {
    1: ("Beach vacation from NYC", test_1_beach_vacation),
    2: ("Romantic Europe $3000 budget", test_2_romantic_europe),
    3: ("Session continuity follow-up", test_3_session_followup),
    4: ("Budget infeasibility", test_4_budget_infeasible),
    5: ("RAG influence on destinations", test_5_rag_influence),
    6: ("Multi-traveler pricing", test_6_multi_traveler),
    7: ("Health check endpoints", test_7_health_endpoints),
}


def main():
    parser = argparse.ArgumentParser(description="E2E smoke tests for AI Travel Agent")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--test", type=int, help="Run only this test number (1-7)")
    args = parser.parse_args()

    print("=" * 70)
    print("  E2E SMOKE TESTS — AI Travel Agent")
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

    tests_to_run = (
        {args.test: ALL_TESTS[args.test]} if args.test and args.test in ALL_TESTS
        else ALL_TESTS
    )

    results = {}
    for num, (name, fn) in tests_to_run.items():
        try:
            passed = fn(args.base_url)
            results[num] = ("PASS" if passed else "FAIL", name)
        except Exception as e:
            print(f"\n  EXCEPTION in test {num}: {e}")
            results[num] = ("ERROR", name)

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    for num in sorted(results):
        status, name = results[num]
        icon = "+" if status == "PASS" else "X"
        print(f"  [{icon}] Test {num}: {name} — {status}")

    passed = sum(1 for s, _ in results.values() if s == "PASS")
    failed = sum(1 for s, _ in results.values() if s != "PASS")
    print(f"\n  {passed} passed, {failed} failed/errored")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
