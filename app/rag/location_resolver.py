"""Resolve airport/location codes to city names using RAG (Wikivoyage).

Used by the flights tool so the Booking.com API receives names it can resolve
(e.g. "Tel Aviv" instead of "TLV", which returns an invalid id). All resolutions
are verified against RAG content to avoid hallucination: we only return a city
name when a chunk actually contains the code.
"""

from __future__ import annotations

import re
from typing import Any

from app.rag.retriever import retrieve_chunks


def looks_like_airport_code(location: str) -> bool:
    """True if the string is likely an IATA/airport code (2–3 letters)."""
    if not location or not isinstance(location, str):
        return False
    s = location.strip()
    return len(s) in (2, 3) and s.isalpha()


def _code_appears_in_text(code: str, text: str) -> bool:
    """Check that the code appears as a word (avoid false matches)."""
    if not text or not code:
        return False
    code_upper = code.upper()
    # Word boundary: code surrounded by non-alphanumeric or at start/end
    pattern = re.compile(r"(?<![a-zA-Z])" + re.escape(code_upper) + r"(?![a-zA-Z])")
    return pattern.search(text) is not None


def resolve_location_name_from_rag(location_str: str, top_k: int = 5) -> str | None:
    """Resolve an airport/city code to a city name using Wikivoyage RAG.

    Tries several RAG queries to maximize chance of a hit. Only returns a name
    when at least one chunk contains the code in its content (anti-hallucination).

    Returns:
        City name (e.g. "Tel Aviv") if verified in RAG, else None.
    """
    if not looks_like_airport_code(location_str):
        return None

    code = location_str.strip().upper()
    queries = [
        f"airport {location_str} city flights",
        f"{location_str} airport get in",
    ]
    for query in queries:
        chunks = retrieve_chunks(query, top_k=top_k)
        for chunk in chunks:
            content = chunk.get("content", "") or ""
            if not _code_appears_in_text(code, content):
                continue
            title = chunk.get("article_title", "").strip()
            if title:
                return title
    return None
