"""State types for the profile workflow package."""

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
    course_profile: dict[str, object] | None
    user_profile: dict[str, object] | None
    mastery_updated: bool
    review_scheduled: bool
    weaknesses_ranked: bool
    report_generated: bool
    error: str | None
