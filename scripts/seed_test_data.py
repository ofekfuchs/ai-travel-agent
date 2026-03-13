#!/usr/bin/env python3
"""Fetch REAL Wikivoyage articles for curated cities, parse them into sections,
generate embeddings, and upload to Pinecone.

Uses the Wikivoyage API to get actual article content -- no fake data.

Deduplication: tracks uploaded chunk IDs in .pinecone_uploaded.json so
re-running the script costs zero if the same cities are already uploaded.

Features:
  --dry-run    Print cost estimate without uploading
  --batch N    Process only the first N cities (for staged rollout)
  --cost-cap   Max estimated embedding cost in USD (default $0.50)

Usage (from repo root, with venv active):
    python scripts/seed_test_data.py                # upload all curated cities
    python scripts/seed_test_data.py --dry-run      # cost estimate only
    python scripts/seed_test_data.py --batch 20     # first 20 cities only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import (
    PINECONE_API_KEY, PINECONE_INDEX_NAME, LLM_API_KEY, LLM_BASE_URL, EMBEDDING_MODEL,
    RAG_MAX_CHUNK_CHARS, RAG_MIN_SECTION_CHARS, RAG_UPSERT_BATCH_SIZE,
    RAG_COST_PER_1K_TOKENS, RAG_AVG_TOKENS_PER_CHUNK, RAG_RELEVANT_SECTIONS,
)

TRACKING_FILE = Path(__file__).resolve().parent.parent / ".pinecone_uploaded.json"

# ── Curated high-value city list ─────────────────────────────────────────
# Criteria: major international airport, capital/high-tourism, multi-region,
# mix of budget-friendly and premium destinations.
CURATED_CITIES = [
    # ── Europe ──
    "London", "Paris", "Berlin", "Rome", "Barcelona",
    "Amsterdam", "Prague", "Vienna", "Lisbon", "Budapest",
    "Athens", "Istanbul", "Dublin", "Edinburgh", "Copenhagen",
    "Stockholm", "Brussels", "Zurich", "Warsaw", "Bucharest",
    "Krakow", "Porto", "Florence", "Milan", "Munich",
    "Nice", "Dubrovnik", "Reykjavik", "Helsinki", "Oslo",
    # ── North America ──
    "New York City", "Los Angeles", "Miami", "San Francisco", "Chicago",
    "Washington, D.C.", "Boston", "Las Vegas", "New Orleans", "Toronto",
    "Vancouver", "Montreal", "Mexico City", "Cancún",
    # ── Central America & Caribbean ──
    "San Juan", "Havana", "Nassau",
    # ── South America ──
    "Buenos Aires", "Rio de Janeiro", "Lima", "Bogotá", "Santiago",
    "Medellín", "Cartagena",
    # ── Asia ──
    "Tokyo", "Bangkok", "Singapore", "Hong Kong", "Seoul",
    "Taipei", "Kuala Lumpur", "Bali", "Hanoi", "Ho Chi Minh City",
    "Delhi", "Mumbai", "Kyoto", "Osaka",
    # ── Middle East ──
    "Dubai", "Tel Aviv", "Amman", "Marrakech",
    # ── Africa ──
    "Cape Town", "Nairobi", "Cairo",
    # ── Oceania ──
    "Sydney", "Melbourne", "Auckland",
]

# Backward compatibility
TEST_CITIES = CURATED_CITIES[:5]

RELEVANT_SECTIONS = RAG_RELEVANT_SECTIONS


def fetch_wikivoyage_article(title: str) -> str | None:
    """Fetch the raw wikitext of a Wikivoyage article via the MediaWiki API."""
    resp = httpx.get(
        "https://en.wikivoyage.org/w/api.php",
        params={
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
        },
        headers={"User-Agent": "AITravelAgent/1.0 (course project; contact: ofek.fuchs@campus.technion.ac.il)"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    parse = data.get("parse", {})
    wikitext = parse.get("wikitext", {}).get("*", "")
    return wikitext if wikitext else None


def strip_wiki_markup(text: str) -> str:
    """Remove common MediaWiki markup to produce clean text."""
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sections(title: str, raw_text: str) -> list[dict]:
    """Split a Wikivoyage article into named section chunks."""
    parts = re.split(r"^(==+)\s*(.+?)\s*\1\s*$", raw_text, flags=re.MULTILINE)

    sections: list[dict] = []
    safe_title = title.replace(" ", "_").lower()

    if parts[0].strip():
        clean = strip_wiki_markup(parts[0])
        if len(clean) > RAG_MIN_SECTION_CHARS:
            sections.append({
                "id": f"{safe_title}::intro",
                "title": title,
                "section": "intro",
                "content": clean[:RAG_MAX_CHUNK_CHARS],
            })

    i = 1
    while i < len(parts) - 2:
        _level = parts[i]
        heading = parts[i + 1].strip().lower()
        body = parts[i + 2]
        i += 3

        if heading in RELEVANT_SECTIONS:
            clean = strip_wiki_markup(body)
            if len(clean) > RAG_MIN_SECTION_CHARS:
                section_id = f"{safe_title}::{heading.replace(' ', '_')}"
                sections.append({
                    "id": section_id,
                    "title": title,
                    "section": heading,
                    "content": clean[:RAG_MAX_CHUNK_CHARS],
                })

    return sections


def load_tracking() -> set[str]:
    if TRACKING_FILE.exists():
        return set(json.loads(TRACKING_FILE.read_text()))
    return set()


def save_tracking(uploaded: set[str]) -> None:
    TRACKING_FILE.write_text(json.dumps(sorted(uploaded), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Pinecone with Wikivoyage articles")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print cost estimate without uploading")
    parser.add_argument("--batch", type=int, default=0,
                        help="Process only the first N cities (0 = all)")
    parser.add_argument("--cost-cap", type=float, default=0.50,
                        help="Max estimated embedding cost in USD (default $0.50)")
    args = parser.parse_args()

    if not PINECONE_API_KEY:
        print("ERROR: PINECONE_API_KEY not set in .env")
        sys.exit(1)
    if not LLM_API_KEY:
        print("ERROR: LLM_API_KEY not set in .env")
        sys.exit(1)

    cities = CURATED_CITIES[:args.batch] if args.batch > 0 else CURATED_CITIES
    print(f"Target: {len(cities)} cities (of {len(CURATED_CITIES)} total curated)")

    already_uploaded = load_tracking()
    print(f"Already uploaded: {len(already_uploaded)} chunks\n")

    all_chunks: list[dict] = []
    failed_cities: list[str] = []

    for i, city in enumerate(cities, 1):
        print(f"[{i}/{len(cities)}] Fetching Wikivoyage: {city} ...", end=" ")
        try:
            wikitext = fetch_wikivoyage_article(city)
        except Exception as exc:
            print(f"FAILED ({exc})")
            failed_cities.append(city)
            continue

        if not wikitext:
            print(f"empty article, skipping.")
            failed_cities.append(city)
            continue

        sections = split_sections(city, wikitext)
        print(f"{len(sections)} sections")
        all_chunks.extend(sections)

    new_chunks = [c for c in all_chunks if c["id"] not in already_uploaded]

    if not new_chunks:
        print(f"\nAll {len(all_chunks)} chunks already in Pinecone. Nothing to do.")
        if failed_cities:
            print(f"Failed cities: {', '.join(failed_cities)}")
        return

    # ── Cost estimation ──────────────────────────────────────────────────
    est_tokens = len(new_chunks) * RAG_AVG_TOKENS_PER_CHUNK
    est_cost = (est_tokens / 1000) * RAG_COST_PER_1K_TOKENS

    print(f"\n{'='*50}")
    print(f"  New chunks to upload:  {len(new_chunks)}")
    print(f"  Already uploaded:      {len(already_uploaded)}")
    print(f"  Estimated tokens:      ~{est_tokens:,}")
    print(f"  Estimated embed cost:  ~${est_cost:.4f}")
    print(f"  Cost cap:              ${args.cost_cap:.2f}")
    print(f"{'='*50}")

    if est_cost > args.cost_cap:
        print(f"\n  COST CAP EXCEEDED (${est_cost:.4f} > ${args.cost_cap:.2f})")
        print(f"  Use --cost-cap {est_cost:.2f} to override, or --batch to reduce scope.")
        return

    if args.dry_run:
        print("\n  DRY RUN — no uploads performed.")
        print(f"  Cities fetched successfully: {len(cities) - len(failed_cities)}")
        if failed_cities:
            print(f"  Failed cities: {', '.join(failed_cities)}")
        return

    # ── Upload ───────────────────────────────────────────────────────────
    from pinecone import Pinecone
    from langchain_openai import OpenAIEmbeddings

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    embeddings = OpenAIEmbeddings(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, model=EMBEDDING_MODEL)

    texts = [f"{c['title']} - {c['section']}\n{c['content']}" for c in new_chunks]
    print(f"\nGenerating embeddings for {len(texts)} chunks ...")
    vectors = embeddings.embed_documents(texts)

    upsert_data = []
    for chunk, vec in zip(new_chunks, vectors):
        upsert_data.append((
            chunk["id"],
            vec,
            {
                "article_title": chunk["title"],
                "section_name": chunk["section"],
                "content": chunk["content"],
            },
        ))

    for i in range(0, len(upsert_data), RAG_UPSERT_BATCH_SIZE):
        batch = upsert_data[i : i + RAG_UPSERT_BATCH_SIZE]
        index.upsert(vectors=batch)
        print(f"  Upserted batch {i // RAG_UPSERT_BATCH_SIZE + 1} ({len(batch)} vectors)")

    newly_uploaded = already_uploaded | {c["id"] for c in new_chunks}
    save_tracking(newly_uploaded)

    print(f"\nDone. Total chunks in Pinecone: {len(newly_uploaded)}")
    print(f"Cities processed: {len(cities) - len(failed_cities)} / {len(cities)}")
    if failed_cities:
        print(f"Failed cities: {', '.join(failed_cities)}")


if __name__ == "__main__":
    main()
