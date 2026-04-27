"""Confirmed build plan value object."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.utils.time import utcnow


class ConfirmedBuildPlan(BaseModel):
    """Frozen planner contract confirmed by the user and consumed by DocGen."""

    id: str
    subject: str
    planner_session_id: str | None = None
    user_id: str = "local"
    status: str = "confirmed"
    user_prompt: str = ""
    digest_mode: str = "sprint"
    selected_file_ids_json: list[int] = Field(default_factory=list)
    chapter_plan_json: list[dict[str, Any]] = Field(default_factory=list)
    build_constraints_json: dict[str, Any] = Field(default_factory=dict)
    plan_summary: str = ""
    plan_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
