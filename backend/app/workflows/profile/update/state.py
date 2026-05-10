"""State contract for the exam-driven Profile update lane.

This state is used after exam grading to update mastery, schedule reviews,
rank weaknesses, and refresh persisted profile summaries. It does not describe
Profile page read-only snapshots or study-plan output.
"""

from __future__ import annotations

from typing import TypedDict


class ProfileUpdateState(TypedDict, total=False):
    course_id: str
    user_id: str
    exam_paper_id: int
    top_n: int
    mastery_result: dict[str, object] | None
    updated_state_ids: list[int]
    review_task_ids: list[int]
    weaknesses: list[dict[str, object]]
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
    workflow_elapsed_ms: int
    error: str | None


__all__ = ["ProfileUpdateState"]
