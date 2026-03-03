#!/usr/bin/env python3
"""Dry test: test every tool function the agent actually uses.

Tests the REAL code paths (not raw HTTP). Zero LLM chat calls.
Only one embedding call for the RAG test (~$0.0001).

Usage:  python scripts/test_tools_dry.py
"""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.config import (
    PINECONE_API_KEY, PINECONE_INDEX_NAME,
    LLM_API_KEY, LLM_BASE_URL, EMBEDDING_MODEL,
    RAPIDAPI_KEY, OPENTRIPMAP_API_KEY,
    SUPABASE_URL, SUPABASE_ANON_KEY,
)
from app.models.shared_state import SharedState

PASS = "PASS"
FAIL = "FAIL"
results = []


def report(name: str, status: str, detail: str):
    results.append((name, status, detail))
    icon = "+" if status == PASS else "X"
    print(f"  [{icon}] {name}: {detail}")


# ── 1. Pinecone RAG retrieval ──────────────────────────────────────────────
def test_pinecone_rag():
    print("\n1. PINECONE RAG RETRIEVAL")

    if not PINECONE_API_KEY:
        report("Pinecone", FAIL, "PINECONE_API_KEY not set")
        return

    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX_NAME)
        stats = index.describe_index_stats()
        total = stats.get("total_vector_count", 0)
        report("Pinecone connect", PASS, f"Index '{PINECONE_INDEX_NAME}' has {total} vectors")
    except Exception as e:
        report("Pinecone connect", FAIL, str(e))
        return

    try:
        from app.tools.rag_tool import search_destinations
        state = SharedState(raw_prompt="test")
        chunks = search_destinations(state, query="Paris museums food")
        if chunks:
            titles = [c.get("article_title", "?") for c in chunks]
            report("RAG tool", PASS, f"{len(chunks)} chunks: {titles}")
        else:
            report("RAG tool", FAIL, "0 chunks returned")
    except Exception as e:
        report("RAG tool", FAIL, str(e))


# ── 2. Flights tool ────────────────────────────────────────────────────────
def test_flights():
    print("\n2. FLIGHTS TOOL (with auto-resolve)")

    if not RAPIDAPI_KEY:
        report("Flights", FAIL, "RAPIDAPI_KEY not set")
        return

    from app.tools.flights_tool import search_flights, _resolve_entity_id

    # Test A: entity resolution
    try:
        entity = _resolve_entity_id("New York")
        report("Flights resolve 'New York'", PASS, f"-> '{entity}'")
    except Exception as e:
        report("Flights resolve", FAIL, str(e))

    try:
        entity = _resolve_entity_id("Paris")
        report("Flights resolve 'Paris'", PASS, f"-> '{entity}'")
    except Exception as e:
        report("Flights resolve", FAIL, str(e))

    # Test B: actual search with city names
    try:
        state = SharedState(raw_prompt="test")
        options = search_flights(state, origin="New York", destination="Paris", date="2026-06-15")
        if options:
            first = options[0]
            report("Flights search (city names)", PASS,
                   f"{len(options)} flights. First: {first.get('airline', '?')}, "
                   f"${first.get('price', '?')}, {first.get('origin', '?')}->{first.get('destination', '?')}")
        else:
            report("Flights search (city names)", FAIL,
                   f"0 flights returned. Check step log: {json.dumps(state.steps[-1] if state.steps else {}, indent=2)[:300]}")
    except Exception as e:
        report("Flights search", FAIL, str(e))


# ── 3. Hotels tool ─────────────────────────────────────────────────────────
def test_hotels():
    print("\n3. HOTELS TOOL (with auto-resolve)")

    if not RAPIDAPI_KEY:
        report("Hotels", FAIL, "RAPIDAPI_KEY not set")
        return

    from app.tools.hotels_tool import search_hotels, _resolve_dest_id

    # Test A: dest_id resolution
    try:
        dest_id, dest_type = _resolve_dest_id("Paris")
        report("Hotels resolve 'Paris'", PASS, f"-> dest_id={dest_id}, type={dest_type}")
    except Exception as e:
        report("Hotels resolve", FAIL, str(e))

    # Test B: actual search
    try:
        state = SharedState(raw_prompt="test")
        options = search_hotels(state, destination="Paris", check_in="2026-06-15", check_out="2026-06-19", adults=1)
        if options:
            first = options[0]
            report("Hotels search", PASS,
                   f"{len(options)} hotels. First: '{first.get('name', '?')}', "
                   f"total=${first.get('total_price', '?')}, rating={first.get('rating', '?')}")
        else:
            report("Hotels search", FAIL,
                   f"0 hotels returned. Check step log: {json.dumps(state.steps[-1] if state.steps else {}, indent=2)[:300]}")
    except Exception as e:
        report("Hotels search", FAIL, str(e))


# ── 4. Weather tool ────────────────────────────────────────────────────────
def test_weather():
    print("\n4. WEATHER TOOL")

    from app.tools.weather_tool import get_weather

    try:
        state = SharedState(raw_prompt="test")
        result = get_weather(state, latitude=48.8566, longitude=2.3522,
                             start_date="2026-06-15", end_date="2026-06-19",
                             destination_name="Paris")
        if "error" not in result:
            report("Weather (Paris June)", PASS,
                   f"type={result.get('type')}, avg_high={result.get('avg_high_c')}C, avg_low={result.get('avg_low_c')}C")
        else:
            report("Weather", FAIL, result["error"])
    except Exception as e:
        report("Weather", FAIL, str(e))


# ── 5. POI tool ────────────────────────────────────────────────────────────
def test_pois():
    print("\n5. POI TOOL")

    if not OPENTRIPMAP_API_KEY:
        report("POI", FAIL, "OPENTRIPMAP_API_KEY not set")
        return

    from app.tools.poi_tool import search_pois

    try:
        state = SharedState(raw_prompt="test")
        pois = search_pois(state, latitude=48.8566, longitude=2.3522, destination_name="Paris")
        if pois:
            names = [p.get("name", "?") for p in pois[:5]]
            report("POI search (Paris)", PASS, f"{len(pois)} POIs: {names}")
        else:
            report("POI search", FAIL, "0 POIs returned")
    except Exception as e:
        report("POI search", FAIL, str(e))


# ── 6. Supabase ────────────────────────────────────────────────────────────
def test_supabase():
    print("\n6. SUPABASE CONNECTIVITY")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        report("Supabase", FAIL,
               f"URL={'set' if SUPABASE_URL else 'NOT SET'}, KEY={'set' if SUPABASE_ANON_KEY else 'NOT SET'}")
        return

    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            report("Supabase connect", PASS, "Connected OK")
        else:
            report("Supabase connect", FAIL, f"Status {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        report("Supabase connect", FAIL, str(e))


# ── Run all ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  DRY TEST: All tools the agent uses (zero LLM chat calls)")
    print("=" * 60)

    test_pinecone_rag()
    test_flights()
    test_hotels()
    test_weather()
    test_pois()
    test_supabase()

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for name, status, detail in results:
        icon = "+" if status == PASS else "X"
        print(f"  [{icon}] {name}")

    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    print(f"\n  {passed} passed, {failed} failed")

    if failed:
        print("\n  FAILED TESTS NEED FIXING BEFORE RUNNING THE AGENT!")
        sys.exit(1)
    else:
        print("\n  ALL TOOLS WORK! Safe to run the full agent now.")


if __name__ == "__main__":
    main()
