"""Planner state definitions."""

from __future__ import annotations

from typing import Any, TypedDict

from app.workflows.digest.shared.models import SharedInputs


class BuildPlannerState(TypedDict, total=False):
    subject: str
    file_ids: list[int]
    user_goal: str
    digest_mode: str
    course_type: str
    retrieval_profile: str
    teaching_action: str
    tone: str
    selected_skillpacks: list[str]
    planner_session_id: str
    message_history: list[str]
    latest_plan: dict[str, Any] | None
    shared_inputs: SharedInputs
    concept_queries: list[str]
    concept_briefing: str
    concept_topic_hints: list[str]
    concept_local_hit_count: int
    concept_web_hit_count: int
    plan: dict[str, Any]
    plan_summary: str
    workflow_elapsed_ms: int
    runtime_steps: list[dict[str, Any]]
    _runtime_step_starts: dict[str, float]
    fallback_used: bool
    planner_generation_mode: str
    progress_callback: Any
    token_callback: Any
    error: str | None


__all__ = ["BuildPlannerState"]
