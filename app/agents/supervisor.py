"""Supervisor -- the controller / router that decides what happens next.

It is the ONLY component that makes routing decisions. It never fetches
data or builds trip plans itself.

Now receives richer context (constraints + data counts) so it can properly
handle clarification decisions that used to be done by preflight/Gate A.
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
- SCOPE GUARD: If the request is NOT about planning a trip (e.g., writing code, general questions, web scraping), choose "ask_clarification" and explain that you are specialized ONLY in travel planning.


- CAPABILITY GUARD: 
  The Planner acts as a Consultant, NOT a booking agent.
  It CAN search for flights, hotels, and plan itineraries.
  It CANNOT book tickets, make reservations, or process payments.
  If the user explicitly asks to "book", "pay", or "reserve", choose "ask_clarification" and explain your limitations.

- If the user's request is extremely vague (e.g. "plan me a trip" with no
  details at all), choose "ask_clarification". The clarification question
  MUST ask for whichever of these are missing:
    * origin (where they are flying from)
    * date window (specific dates, or month/season)
    * duration (how many days/nights)
    * budget (optional but very helpful)
    * destination preference (optional -- "flexible" or "surprise me" is fine)


- SUFFICIENCY: 
  If you have (Origin + Date + Anchor), choose "plan".
  Note: You do NOT need a specific city if a Vibe/Style is provided.


- If the extracted constraints show missing ORIGIN or missing DATE INFO
  (no start_date, no season, no month hint), choose "ask_clarification"
  and ask specifically for the missing fields.

- If there is enough information to work with (at least: origin + some
  date/season hint + rough duration OR preferences), choose "plan".
  Note: destination is NOT required -- the agent can suggest destinations.

- If a verified, approved trip plan already exists in the state, choose
  "finalize".

- If the Verifier rejected the last plan, choose "replan" (the Planner will
  generate corrective tasks).

- Always be concise. Never hallucinate data.
"""


def run_supervisor(state: SharedState) -> dict:
    """Call the LLM to decide the next action and return the parsed decision."""
    user_context_parts = [f"User prompt: {state.raw_prompt}"]

    if state.constraints:
        user_context_parts.append(
            f"Extracted constraints: {json.dumps(state.constraints, default=str)}"
        )
        missing = []
        if not state.constraints.get("origin"):
            missing.append("origin")
        has_dates = state.constraints.get("start_date") or state.constraints.get("end_date")
        has_season = state.constraints.get("season")
        if not has_dates and not has_season:
            missing.append("date window / season")
        if missing:
            user_context_parts.append(f"MISSING critical fields: {missing}")
    else:
        user_context_parts.append("No constraints extracted yet (first iteration).")

    data_counts = {
        "rag_chunks": len(state.destination_chunks),
        "flights": len(state.flight_options),
        "hotels": len(state.hotel_options),
        "weather": len(state.weather_context),
        "pois": len(state.poi_list),
    }
    user_context_parts.append(f"Data collected so far: {json.dumps(data_counts)}")

    if state.verifier_verdicts:
        last = state.verifier_verdicts[-1]
        user_context_parts.append(f"Last verifier verdict: {json.dumps(last, default=str)}")

    if state.draft_plans:
        user_context_parts.append(f"Draft plans exist: {len(state.draft_plans)} package(s).")

    user_context_parts.append(f"LLM calls used: {state.llm_call_count}/{state.llm_call_cap}")

    user_prompt = "\n".join(user_context_parts)

    raw = call_llm(state, module="Supervisor", system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {
            "next_action": "plan",
            "reason": "Could not parse LLM output; defaulting to plan.",
            "clarification_question": None,
        }

    return decision
