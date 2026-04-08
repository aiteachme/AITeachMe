"""Planner state definitions."""

from __future__ import annotations

from typing import Any, TypedDict

from app.workflows.digest.shared.models import SharedInputs


class BuildPlannerState(TypedDict, total=False):
    subject: str
    file_ids: list[int]
    user_goal: str
    digest_mode: str
    tone: str
    planner_session_id: str
    message_history: list[str]
    latest_plan: dict[str, Any] | None
    shared_inputs: SharedInputs
    plan: dict[str, Any]
    plan_summary: str
    error: str | None


__all__ = ["BuildPlannerState"]
