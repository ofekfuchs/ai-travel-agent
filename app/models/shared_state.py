"""Central Shared State that every agent component reads and writes.

SharedState is the single source of truth. It persists tool results across
iterations -- results are NEVER discarded or re-fetched for identical params.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

LLM_CALL_CAP = 8


@dataclass
class SharedState:
    """Single source of truth passed between Supervisor, Planner, Executor,
    Trip Synthesizer, and Verifier."""

    # -- User input ----------------------------------------------------------
    raw_prompt: str = ""
    session_id: str = ""
    conversation_history: list[dict] = field(default_factory=list)

    # -- Extracted constraints ------------------------------------------------
    constraints: dict = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)

    # -- Planner output -------------------------------------------------------
    task_list: list[dict] = field(default_factory=list)

    # -- RAG evidence ---------------------------------------------------------
    destination_chunks: list[dict] = field(default_factory=list)

    # -- Tool outputs ---------------------------------------------------------
    flight_options: list[dict] = field(default_factory=list)
    hotel_options: list[dict] = field(default_factory=list)
    weather_context: list[dict] = field(default_factory=list)
    poi_list: list[dict] = field(default_factory=list)

    # -- Synthesiser output ---------------------------------------------------
    draft_plans: list[dict] = field(default_factory=list)

    # -- Verifier output ------------------------------------------------------
    verifier_verdicts: list[dict] = field(default_factory=list)

    # -- Final result ---------------------------------------------------------
    final_response: Optional[str] = None

    # -- LLM call budget (hard cap per run) -----------------------------------
    llm_call_count: int = 0
    llm_call_cap: int = LLM_CALL_CAP

    # -- Execution trace (course requirement: LLM calls ONLY) -----------------
    steps: list[dict] = field(default_factory=list)

    # -- Tool invocation trace (NOT sent in API steps; for internal debug) ----
    tool_trace: list[dict] = field(default_factory=list)

    def can_call_llm(self) -> bool:
        return self.llm_call_count < self.llm_call_cap

    def remaining_llm_calls(self) -> int:
        return max(0, self.llm_call_cap - self.llm_call_count)
