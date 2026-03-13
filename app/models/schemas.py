"""Pydantic models that define the exact JSON shapes required by the course API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── GET /api/team_info ─────────────────────────────────────────────────────

class TeamInfoStudent(BaseModel):
    name: str
    email: str


class TeamInfoResponse(BaseModel):
    group_batch_order_number: str
    team_name: str
    students: List[TeamInfoStudent]


# ── Step object (used by both /api/agent_info and /api/execute) ────────────

class Step(BaseModel):
    module: str
    prompt: Dict[str, Any]
    response: Dict[str, Any]


# ── GET /api/agent_info ────────────────────────────────────────────────────

class AgentInfoPromptTemplate(BaseModel):
    template: str


class AgentInfoPromptExample(BaseModel):
    prompt: str
    full_response: str
    steps: List[Step]


class AgentInfoResponse(BaseModel):
    description: str
    purpose: str
    prompt_template: AgentInfoPromptTemplate
    prompt_examples: List[AgentInfoPromptExample]


# ── POST /api/execute ──────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None


class ExecuteResponse(BaseModel):
    status: Literal["ok", "error"]
    error: Optional[str] = None
    response: Optional[str] = None
    steps: List[Step] = Field(default_factory=list)
    session_id: Optional[str] = None
    llm_calls_used: Optional[int] = None
    elapsed_seconds: Optional[float] = None
