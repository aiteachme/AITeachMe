"""Planner graph state.

The planner state intentionally stays small. LangSmith already records node
timing and nested LLM calls, so this graph only carries the business artifacts
needed by later nodes.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.shared.infra.workflow import project_typed_dict_schema
from app.workflows.digest.common.models import DigestMaterialContext


class BuildPlannerState(TypedDict, total=False):
    # Stable graph input
    course_id: str
    user_id: str
    planner_operation: str
    requested_file_ids: list[str]
    session_title: str
    feedback_message: str
    selected_file_ids: list[str]
    file_ids: list[str]
    user_prompt: str
    digest_mode: str
    model_override: str | None
    planner_session_id: str
    message_history: list[str]
    latest_plan: dict[str, Any] | None

    # Planner working artifacts
    material_context: DigestMaterialContext
    planner_brief: dict[str, Any]
    plan_intent: dict[str, Any]
    generated_course_name: str
    generated_course_icon_key: str
    plan_outline_markdown: str
    build_plan_draft: dict[str, Any]

    # Stable graph output
    plan: dict[str, Any]
    plan_summary: str
    planner_record: dict[str, Any]
    planner_turns: list[dict[str, Any]]

    # Top-level runtime summary for the existing frontend contract
    workflow_elapsed_ms: int
    prepare_ms: int
    bootstrap_ms: int
    compose_ms: int
    title_ms: int
    finalize_ms: int

    # Runtime callbacks and failure marker
    progress_callback: Any
    token_callback: Any
    error: str | None


BuildPlannerGraphInput = project_typed_dict_schema(
    BuildPlannerState,
    name="BuildPlannerGraphInput",
    fields=[
        "course_id",
        "user_id",
        "planner_operation",
        "requested_file_ids",
        "session_title",
        "feedback_message",
        "file_ids",
        "user_prompt",
        "digest_mode",
        "model_override",
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
        "selected_file_ids",
        "planner_record",
        "planner_turns",
        "workflow_elapsed_ms",
        "prepare_ms",
        "bootstrap_ms",
        "compose_ms",
        "title_ms",
        "finalize_ms",
        "error",
    ],
)


__all__ = [
    "BuildPlannerGraphInput",
    "BuildPlannerGraphOutput",
    "BuildPlannerState",
]
