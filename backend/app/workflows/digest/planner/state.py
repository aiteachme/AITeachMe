"""Planner state definitions."""

from __future__ import annotations

from typing import Any, TypedDict

from app.shared.infra.workflow import project_typed_dict_schema
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
    load_ms: int
    ground_ms: int
    draft_ms: int
    planner_generation_mode: str
    progress_callback: Any
    token_callback: Any
    error: str | None


BuildPlannerGraphInput = project_typed_dict_schema(
    BuildPlannerState,
    name="BuildPlannerGraphInput",
    fields=[
        "subject",
        "file_ids",
        "user_goal",
        "digest_mode",
        "tone",
        "selected_skillpacks",
        "planner_session_id",
        "message_history",
        "latest_plan",
        "progress_callback",
        "token_callback",
    ],
)


BuildPlannerGraphOutput = project_typed_dict_schema(
    BuildPlannerState,
    name="BuildPlannerGraphOutput",
    fields=[
        "plan",
        "plan_summary",
        "digest_mode",
        "planner_generation_mode",
        "workflow_elapsed_ms",
        "load_ms",
        "ground_ms",
        "draft_ms",
        "error",
    ],
)


__all__ = [
    "BuildPlannerGraphInput",
    "BuildPlannerGraphOutput",
    "BuildPlannerState",
]
