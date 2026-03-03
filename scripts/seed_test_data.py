#!/usr/bin/env python3
"""Fetch REAL Wikivoyage articles for test cities, parse them into sections,
generate embeddings, and upload to Pinecone.

Uses the Wikivoyage API to get actual article content -- no fake data.

Deduplication: tracks uploaded chunk IDs in .pinecone_uploaded.json so
re-running the script costs zero if the same cities are already uploaded.

Usage (from repo root, with venv active):
    python scripts/seed_test_data.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PINECONE_API_KEY, PINECONE_INDEX_NAME, LLM_API_KEY, LLM_BASE_URL, EMBEDDING_MODEL

TRACKING_FILE = Path(__file__).resolve().parent.parent / ".pinecone_uploaded.json"

TEST_CITIES = ["London", "Paris", "New York City", "Berlin", "Washington, D.C."]

RELEVANT_SECTIONS = {
    "understand", "get in", "get around", "see", "do", "eat", "drink",
    "sleep", "buy", "stay safe", "cope", "respect", "connect",
    "budget", "climate", "when to go",
}


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
        if len(clean) > 50:
            sections.append({
                "id": f"{safe_title}::intro",
                "title": title,
                "section": "intro",
                "content": clean[:3000],
            })

    i = 1
    while i < len(parts) - 2:
        _level = parts[i]
        heading = parts[i + 1].strip().lower()
        body = parts[i + 2]
        i += 3

        if heading in RELEVANT_SECTIONS:
            clean = strip_wiki_markup(body)
            if len(clean) > 50:
                section_id = f"{safe_title}::{heading.replace(' ', '_')}"
                sections.append({
                    "id": section_id,
                    "title": title,
                    "section": heading,
                    "content": clean[:3000],
                })

    return sections


def load_tracking() -> set[str]:
    if TRACKING_FILE.exists():
        return set(json.loads(TRACKING_FILE.read_text()))
    return set()


def save_tracking(uploaded: set[str]) -> None:
    TRACKING_FILE.write_text(json.dumps(sorted(uploaded), indent=2))


def main() -> None:
    if not PINECONE_API_KEY:
        print("ERROR: PINECONE_API_KEY not set in .env")
        sys.exit(1)
    if not LLM_API_KEY:
        print("ERROR: LLM_API_KEY not set in .env")
        sys.exit(1)

    already_uploaded = load_tracking()
    all_chunks: list[dict] = []

    for city in TEST_CITIES:
        print(f"Fetching Wikivoyage article: {city} ...")
        wikitext = fetch_wikivoyage_article(city)
        if not wikitext:
            print(f"  WARNING: Could not fetch article for '{city}', skipping.")
            continue

        sections = split_sections(city, wikitext)
        print(f"  Parsed {len(sections)} relevant sections.")
        all_chunks.extend(sections)

    new_chunks = [c for c in all_chunks if c["id"] not in already_uploaded]

    if not new_chunks:
        print(f"\nAll {len(all_chunks)} chunks already in Pinecone. Nothing to do.")
        return

    print(f"\n{len(new_chunks)} new chunks to upload ({len(already_uploaded)} already done).")

    from pinecone import Pinecone
    from langchain_openai import OpenAIEmbeddings

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    embeddings = OpenAIEmbeddings(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, model=EMBEDDING_MODEL)

    texts = [f"{c['title']} - {c['section']}\n{c['content']}" for c in new_chunks]
    print(f"Generating embeddings for {len(texts)} chunks via LLMod.ai ...")
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

    BATCH = 50
    for i in range(0, len(upsert_data), BATCH):
        batch = upsert_data[i : i + BATCH]
        index.upsert(vectors=batch)
        print(f"  Upserted batch {i // BATCH + 1} ({len(batch)} vectors)")

    newly_uploaded = already_uploaded | {c["id"] for c in new_chunks}
    save_tracking(newly_uploaded)

    print(f"\nDone. Total chunks in Pinecone: {len(newly_uploaded)}")
    print("Cities loaded:", ", ".join(TEST_CITIES))


if __name__ == "__main__":
    main()
