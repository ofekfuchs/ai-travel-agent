"""Thin wrapper around LangChain ChatOpenAI pointing at LLMod.ai.

Every call goes through ``call_llm`` which:
1. Invokes the model.
2. Automatically appends a step to the shared state's ``steps`` list so the
   course-required execution trace is always up-to-date.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from app.models.shared_state import SharedState


def get_llm() -> ChatOpenAI:
    """Return a ChatOpenAI instance configured for LLMod.ai.

    Note: RPRTHPB-gpt-5-mini only supports temperature=1, so we
    do not pass a temperature parameter and let the server default.
    """
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
    """Call the LLM, log the step, and return the response text.

    Parameters
    ----------
    state : SharedState
        The central shared state; a step dict will be appended to
        ``state.steps``.
    module : str
        Component name that **must** match the architecture diagram
        (e.g. ``"Supervisor"``, ``"Planner"``, ``"Trip Synthesizer"``,
        ``"Verifier"``).
    system_prompt : str
        The system-level instruction for the LLM.
    user_prompt : str
        The user-level content for this particular call.

    Returns
    -------
    str
        The text content of the LLM response.
    """
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
