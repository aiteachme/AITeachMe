"""Planner state definitions."""

from __future__ import annotations

from typing import Any, TypedDict

from app.workflows.digest.common.models import DigestMaterialContext


class BuildPlannerState(TypedDict, total=False):
    # Request/session inputs.
    subject: str
    file_ids: list[int]
    user_goal: str
    digest_mode: str
    tone: str
    selected_skillpacks: list[str]
    planner_session_id: str
    message_history: list[str]
    latest_plan: dict[str, Any] | None
    progress_callback: Any
    token_callback: Any

    # Planner runtime knobs.
    retrieval_profile: str
    planner_generation_mode: str
    error: str | None

    # Node outputs passed along the active graph.
    material_context: DigestMaterialContext
    plan_sketch_markdown: str
    plan_sketch: dict[str, Any]
    learning_intent_profile: dict[str, Any]
    research_probe_plan: dict[str, Any]
    evidence_brief: dict[str, Any]
    build_plan_contract: dict[str, Any]
    plan: dict[str, Any]
    plan_summary: str

    # API-facing summary. Detailed node timing lives in LangSmith.
    workflow_elapsed_ms: int


__all__ = [
    "BuildPlannerState",
]
