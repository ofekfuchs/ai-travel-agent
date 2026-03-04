"""Thin wrapper around LangChain ChatOpenAI pointing at LLMod.ai.

Every call goes through ``call_llm`` which:
1. Checks the per-run LLM call cap (hard enforcement).
2. Invokes the model.
3. Increments the call counter.
4. Appends a step to the shared state's ``steps`` list.
"""

from __future__ import annotations

from typing import Any, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from app.models.shared_state import SharedState


class LLMCapReached(Exception):
    """Raised when the per-run LLM call cap is exhausted."""
    pass


def get_llm() -> ChatOpenAI:
    """Return a ChatOpenAI instance configured for LLMod.ai."""
    return ChatOpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=1,
    )


def call_llm(
    state: SharedState,
    module: str,
    system_prompt: str,
    user_prompt: str,
    **kwargs: Any,
) -> str:
    """Call the LLM, enforce the cap, log the step, return the response text.

    Raises ``LLMCapReached`` if the per-run cap has been exhausted.
    The main loop should check ``state.can_call_llm()`` before calling
    modules, but this is a hard safety net.
    """
    if not state.can_call_llm():
        raise LLMCapReached(
            f"LLM call cap ({state.llm_call_cap}) reached. "
            f"Used {state.llm_call_count} calls. Module '{module}' blocked."
        )

    state.llm_call_count += 1

    llm = get_llm()
    messages: List[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    response = llm.invoke(messages)
    response_text: str = response.content  # type: ignore[union-attr]

    state.steps.append(
        {
            "module": module,
            "prompt": {
                "system": system_prompt,
                "user": user_prompt,
            },
            "response": {
                "content": response_text,
            },
        }
    )

    return response_text
