"""Shared state contract for Profile graph node builders.

This TypedDict covers the keys shared by update, snapshot, and study-plan
node adapters. It does not describe HTTP schemas or database models.
"""

from __future__ import annotations

from typing import TypedDict


class ProfileWorkflowState(TypedDict, total=False):
    course_id: str
    user_id: str
    exam_paper_id: int
    top_n: int
    mastery_result: dict[str, object] | None
    updated_state_ids: list[int]
    review_task_ids: list[int]
    weaknesses: list[dict[str, object]]
    knowledge_unit_states: list[dict[str, object]]
    weak_knowledge_unit_count: int
    course_profile: dict[str, object] | None
    user_profile: dict[str, object] | None
    mastery_updated: bool
    review_scheduled: bool
    weaknesses_ranked: bool
    report_generated: bool
    resolve_context_ms: int
    update_mastery_ms: int
    schedule_reviews_ms: int
    analyze_weakness_ms: int
    refresh_course_profile_ms: int
    refresh_user_profile_ms: int
    validate_snapshot_ms: int
    load_mastery_overview_ms: int
    build_course_profile_ms: int
    build_user_profile_ms: int
    workflow_elapsed_ms: int
    error: str | None
