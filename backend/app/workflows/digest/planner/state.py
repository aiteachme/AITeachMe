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
    refresh_diagnosis: bool
    diagnose_answers: list[dict[str, Any]]
    diagnose_status: str
    diagnose_note: str
    planner_context_stats: dict[str, Any]
    existing_doc_context: str
    planner_context_mode: str

    # Planner working artifacts
    material_context: DigestMaterialContext
    planning_note: str
    material_note: str
    generated_course_name: str
    generated_course_icon_key: str
    plan_outline_markdown: str
    build_plan_draft: dict[str, Any]

    # Stable graph output
    plan: dict[str, Any]
    planner_record: dict[str, Any]
    planner_turns: list[dict[str, Any]]

    # Internal runtime summary for logs/tracing only
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
        "refresh_diagnosis",
        "diagnose_answers",
        "diagnose_status",
        "diagnose_note",
        "progress_callback",
        "token_callback",
    ],
)


BuildPlannerGraphOutput = project_typed_dict_schema(
    BuildPlannerState,
    name="BuildPlannerGraphOutput",
    fields=[
        "plan",
        "digest_mode",
        "model_override",
        "selected_file_ids",
        "planner_record",
        "planner_turns",
        "error",
    ],
)


__all__ = [
    "BuildPlannerGraphInput",
    "BuildPlannerGraphOutput",
    "BuildPlannerState",
]
