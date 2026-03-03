"""Central Shared State that every agent component reads and writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SharedState:
    """Single source of truth passed between Supervisor, Planner, Executor,
    Trip Synthesizer, and Verifier.  Every field has a safe default so a fresh
    state can be created with just ``SharedState(raw_prompt=...)``.
    """

    # -- User input ----------------------------------------------------------
    raw_prompt: str = ""
    conversation_history: list[dict] = field(default_factory=list)

    # -- Extracted constraints ------------------------------------------------
    constraints: dict = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)

    # -- Planner output -------------------------------------------------------
    task_list: list[dict] = field(default_factory=list)

    # -- RAG evidence ---------------------------------------------------------
    destination_chunks: list[dict] = field(default_factory=list)
    candidate_destinations: list[dict] = field(default_factory=list)

    # -- Tool outputs ---------------------------------------------------------
    flight_options: list[dict] = field(default_factory=list)
    hotel_options: list[dict] = field(default_factory=list)
    weather_context: list[dict] = field(default_factory=list)
    poi_list: list[dict] = field(default_factory=list)

    # -- Synthesiser output ---------------------------------------------------
    draft_plans: list[dict] = field(default_factory=list)

    # -- Verifier output ------------------------------------------------------
    verifier_verdicts: list[dict] = field(default_factory=list)

    # -- Budget warning (set by deterministic pre-check, no LLM cost) --------
    budget_warning: Optional[str] = None

    # -- Final result ---------------------------------------------------------
    final_response: Optional[str] = None

    # -- Execution trace (course requirement: LLM calls ONLY) -----------------
    steps: list[dict] = field(default_factory=list)

    # -- Tool invocation trace (NOT sent in API steps; for internal debug) ----
    tool_trace: list[dict] = field(default_factory=list)
