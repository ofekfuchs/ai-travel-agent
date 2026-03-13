"""Quick RAG retrieval quality test.

Runs several travel queries against Pinecone and prints:
- article_title, section_name, score, content preview
This lets us evaluate whether the embeddings are returning relevant content.

Usage: python scripts/test_rag_retrieval.py
"""
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.tools.rag_tool import search_destinations
from app.models.shared_state import SharedState
from app.config import RAG_TOP_K, RAG_SCORE_THRESHOLD

print(f"RAG config: top_k={RAG_TOP_K}, score_threshold={RAG_SCORE_THRESHOLD}")
print("=" * 70)

queries = [
    "Europe in May best value",
    "Beach vacation June NYC",
    "romantic trip Europe museums food",
    "budget backpacking Eastern Europe",
    "Paris museums and food",
    "cheap destinations with nightlife",
    "historical cities for couples",
]

for q in queries:
    print(f"\n--- Query: \"{q}\" ---")
    state = SharedState(raw_prompt="test")
    chunks = search_destinations(state, query=q, top_k=RAG_TOP_K)
    if chunks:
        for c in chunks:
            preview = c["content"][:120].replace("\n", " ")
            print(f"  [{c['score']:.3f}] {c['article_title']} / {c['section_name']}")
            print(f"          {preview}...")
    else:
        print("  NO CHUNKS RETURNED (all below score threshold or Pinecone empty)")

print("\n" + "=" * 70)
print(f"Queries tested: {len(queries)}")
