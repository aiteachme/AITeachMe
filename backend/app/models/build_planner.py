"""Confirmed build plan value object."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.utils.time import utcnow


class ConfirmedBuildPlan(BaseModel):
    """Frozen planner contract confirmed by the user and consumed by DocGen."""

    id: str
    version_no: int = 1
    course_id: str
    planner_session_id: str | None = None
    user_id: str = "local"
    status: str = "confirmed"
    user_prompt: str = ""
    digest_mode: str = "systematic"
    selected_file_ids: list[str] = Field(default_factory=list)
    chapters: list[dict[str, Any]] = Field(default_factory=list)
    build_constraints: dict[str, Any] = Field(default_factory=dict)
    plan: str = ""
    plan_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
