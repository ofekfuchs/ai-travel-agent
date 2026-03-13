"""Parse the English Wikivoyage XML dump, chunk articles by section,
generate embeddings, and upsert to Pinecone.

This module is designed to be run as a one-time CLI script via
``scripts/ingest_wikivoyage.py``.  It is **not** called at request time.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Generator

from app.config import RAG_RELEVANT_SECTIONS, RAG_MIN_SECTION_CHARS

RELEVANT_SECTIONS = RAG_RELEVANT_SECTIONS


def _strip_wiki_markup(text: str) -> str:
    """Remove common MediaWiki markup so we store clean text in Pinecone."""
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def iter_articles(xml_path: str | Path) -> Generator[dict, None, None]:
    """Yield ``{title, sections: [{name, content}]}`` from a Wikivoyage XML dump."""
    context = ET.iterparse(str(xml_path), events=("end",))
    ns = "{http://www.mediawiki.org/xml/export-0.10/}"

    for event, elem in context:
        if elem.tag != f"{ns}page":
            continue

        title_el = elem.find(f"{ns}title")
        text_el = elem.find(f".//{ns}text")

        if title_el is None or text_el is None or text_el.text is None:
            elem.clear()
            continue

        title = title_el.text.strip()
        raw = text_el.text

        if ":" in title:
            elem.clear()
            continue

        sections = _split_sections(raw)
        if sections:
            yield {"title": title, "sections": sections}

        elem.clear()


def _split_sections(raw_text: str) -> list[dict]:
    """Split a Wikivoyage article into named sections."""
    parts = re.split(r"^(==+)\s*(.+?)\s*\1\s*$", raw_text, flags=re.MULTILINE)

    sections: list[dict] = []
    if parts[0].strip():
        sections.append({"name": "intro", "content": _strip_wiki_markup(parts[0])})

    i = 1
    while i < len(parts) - 2:
        _level = parts[i]
        heading = parts[i + 1].strip().lower()
        body = parts[i + 2]
        i += 3

        if heading in RELEVANT_SECTIONS:
            clean = _strip_wiki_markup(body)
            if len(clean) > RAG_MIN_SECTION_CHARS:
                sections.append({"name": heading, "content": clean})

    return sections
