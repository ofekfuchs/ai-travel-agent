"""Supervisor -- the controller / router that decides what happens next.

It is the ONLY component that makes routing decisions.  It never fetches
data or builds trip plans itself.
"""

from __future__ import annotations

import json

from app.llm.client import call_llm
from app.models.shared_state import SharedState

SYSTEM_PROMPT = """\
You are the Supervisor of a travel-planning agent system.

Your ONLY job is to decide the next action based on the current state.
You must respond with a JSON object (no markdown, no extra text) with
exactly this shape:

{
  "next_action": "<one of: ask_clarification | plan | finalize | replan>",
  "reason": "<one sentence explaining why>",
  "clarification_question": "<question for the user, only if next_action is ask_clarification, else null>"
}

Rules:
- If the user's intent is too vague to plan a trip (no region, no rough dates,
  no hint of budget or duration), choose "ask_clarification" and provide a
  short, targeted question.
- If there is enough information (at least a rough region/destination idea,
  some date or season hint, and any preferences), choose "plan".
- If a verified, approved trip plan already exists in the state, choose
  "finalize".
- If the Verifier rejected the last plan, choose "replan" (the Planner will
  adjust).
- Always be concise.  Never hallucinate data.
"""


def run_supervisor(state: SharedState) -> dict:
    """Call the LLM to decide the next action and return the parsed decision.

    Returns
    -------
    dict
        Keys: ``next_action``, ``reason``, ``clarification_question``.
    """
    user_context_parts = [f"User prompt: {state.raw_prompt}"]

    if state.constraints:
        user_context_parts.append(f"Extracted constraints: {json.dumps(state.constraints, default=str)}")
    if state.missing_fields:
        user_context_parts.append(f"Missing fields: {state.missing_fields}")
    if state.verifier_verdicts:
        last = state.verifier_verdicts[-1]
        user_context_parts.append(f"Last verifier verdict: {json.dumps(last, default=str)}")
    if state.draft_plans:
        user_context_parts.append("A draft trip plan exists.")

    user_prompt = "\n".join(user_context_parts)

    raw = call_llm(state, module="Supervisor", system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {"next_action": "plan", "reason": "Could not parse LLM output; defaulting to plan.", "clarification_question": None}

    return decision
