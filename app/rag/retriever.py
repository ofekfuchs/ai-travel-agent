"""Query the Pinecone index populated with Wikivoyage chunks and return
the top-k most relevant results for a given travel query.
"""

from __future__ import annotations

from typing import Any

from app.config import PINECONE_API_KEY, PINECONE_INDEX_NAME


def retrieve_chunks(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Semantic search over Wikivoyage chunks in Pinecone.

    Returns a list of dicts with keys:
      ``chunk_id``, ``article_title``, ``section_name``, ``content``, ``score``

    If Pinecone is not configured, returns an empty list so the rest of the
    system can still run (useful during local development).
    """
    if not PINECONE_API_KEY:
        return []

    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index(PINECONE_INDEX_NAME)

        from langchain_openai import OpenAIEmbeddings
        from app.config import LLM_API_KEY, LLM_BASE_URL, EMBEDDING_MODEL

        embeddings = OpenAIEmbeddings(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=EMBEDDING_MODEL,
        )
        query_vector = embeddings.embed_query(query)

        results = index.query(vector=query_vector, top_k=top_k, include_metadata=True)

        chunks: list[dict[str, Any]] = []
        for match in results.get("matches", []):
            meta = match.get("metadata", {})
            chunks.append(
                {
                    "chunk_id": match.get("id", ""),
                    "article_title": meta.get("article_title", ""),
                    "section_name": meta.get("section_name", ""),
                    "content": meta.get("content", ""),
                    "score": match.get("score", 0.0),
                }
            )
        return chunks

    except Exception:
        return []
