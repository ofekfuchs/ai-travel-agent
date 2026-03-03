"""Lightweight helpers for the tool invocation trace.

LLM steps are logged automatically by ``llm.client.call_llm`` into
``state.steps`` (the course-required execution trace of LLM calls only).

Tool invocations (API calls to flights, hotels, weather, etc.) are logged
here into ``state.tool_trace`` which is kept separate from the course-required
``steps`` array.  This avoids mixing tool calls into the graded LLM trace.
"""

from __future__ import annotations

from typing import Any, Dict

from app.models.shared_state import SharedState


def log_tool_call(
    state: SharedState,
    module: str,
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_output: Dict[str, Any],
) -> None:
    """Record a tool invocation in the internal tool trace (NOT in steps)."""
    state.tool_trace.append(
        {
            "module": module,
            "tool": tool_name,
            "input": tool_input,
            "output": tool_output,
        }
    )
