#!/usr/bin/env python3
"""One-time CLI script to ingest the Wikivoyage XML dump into Pinecone.

Usage (from repo root, with venv active):
    python scripts/ingest_wikivoyage.py path/to/enwikivoyage-latest-pages-articles.xml

This script:
1. Parses the XML dump using ``app.rag.ingest``.
2. Generates embeddings for each section chunk.
3. Upserts vectors + metadata into the configured Pinecone index.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PINECONE_API_KEY, PINECONE_INDEX_NAME, LLM_API_KEY, LLM_BASE_URL, EMBEDDING_MODEL
from app.rag.ingest import iter_articles


def main(xml_path: str) -> None:
    if not PINECONE_API_KEY:
        print("ERROR: PINECONE_API_KEY not set in .env")
        sys.exit(1)
    if not LLM_API_KEY:
        print("ERROR: LLM_API_KEY not set in .env (needed for embeddings)")
        sys.exit(1)

    from pinecone import Pinecone
    from langchain_openai import OpenAIEmbeddings

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    embeddings = OpenAIEmbeddings(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, model=EMBEDDING_MODEL)

    batch: list[dict] = []
    total = 0
    BATCH_SIZE = 50

    for article in iter_articles(xml_path):
        title = article["title"]
        for section in article["sections"]:
            chunk_text = f"{title} - {section['name']}\n{section['content']}"
            if len(chunk_text) > 8000:
                chunk_text = chunk_text[:8000]

            chunk_id = f"{title}::{section['name']}".replace(" ", "_").lower()
            batch.append(
                {
                    "id": chunk_id,
                    "text": chunk_text,
                    "metadata": {
                        "article_title": title,
                        "section_name": section["name"],
                        "content": section["content"][:3000],
                    },
                }
            )

            if len(batch) >= BATCH_SIZE:
                _upsert_batch(index, embeddings, batch)
                total += len(batch)
                print(f"  upserted {total} chunks …")
                batch = []

    if batch:
        _upsert_batch(index, embeddings, batch)
        total += len(batch)

    print(f"Done. Total chunks upserted: {total}")


def _upsert_batch(index, embeddings, batch: list[dict]) -> None:
    texts = [b["text"] for b in batch]
    vectors = embeddings.embed_documents(texts)
    upsert_data = [
        (b["id"], vec, b["metadata"])
        for b, vec in zip(batch, vectors)
    ]
    index.upsert(vectors=upsert_data)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_wikivoyage.py <path-to-xml>")
        sys.exit(1)
    main(sys.argv[1])
