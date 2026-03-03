"""RAG tool -- retrieve destination knowledge from the Wikivoyage vector DB."""

from __future__ import annotations

from typing import Any

from app.models.shared_state import SharedState
from app.rag.retriever import retrieve_chunks
from app.utils.step_logger import log_tool_call


def search_destinations(state: SharedState, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Search Wikivoyage chunks for *query* and store results in Shared State."""
    chunks = retrieve_chunks(query, top_k=top_k)
    state.destination_chunks.extend(chunks)

    log_tool_call(
        state,
        module="Executor",
        tool_name="rag_search",
        tool_input={"query": query, "top_k": top_k},
        tool_output={"num_results": len(chunks)},
    )
    return chunks
