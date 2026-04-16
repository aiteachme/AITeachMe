"""Planner state definitions."""

from __future__ import annotations

from typing import Any, TypedDict

from app.shared.infra.workflow import project_typed_dict_schema
from app.workflows.digest.common.models import DigestMaterialContext


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
    material_context: DigestMaterialContext
    shared_inputs: DigestMaterialContext
    plan_sketch_markdown: str
    plan_sketch_text: str
    plan_sketch: dict[str, Any]
    learning_intent_profile: dict[str, Any]
    research_probe_plan: dict[str, Any]
    selected_sources: list[dict[str, Any]]
    opened_sources: list[dict[str, Any]]
    evidence_brief: dict[str, Any]
    build_plan_contract: dict[str, Any]
    fallback_reason: str | None
    concept_queries: list[str]
    concept_briefing: str
    concept_topic_hints: list[str]
    concept_local_hit_count: int
    concept_web_hit_count: int
    plan: dict[str, Any]
    plan_summary: str
    workflow_elapsed_ms: int
    prepare_ms: int
    digest_ms: int
    preview_ms: int
    probe_ms: int
    compose_ms: int
    finalize_ms: int
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
        "prepare_ms",
        "digest_ms",
        "preview_ms",
        "probe_ms",
        "compose_ms",
        "finalize_ms",
        "error",
    ],
)


__all__ = [
    "BuildPlannerGraphInput",
    "BuildPlannerGraphOutput",
    "BuildPlannerState",
]
