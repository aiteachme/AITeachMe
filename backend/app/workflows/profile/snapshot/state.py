"""State contract for the read-only Profile snapshot lane.

This state is used by Profile page overview requests. It reads current mastery
and profile signals, but it does not persist profile summaries or schedule
reviews.
"""

from __future__ import annotations

from typing import TypedDict


class ProfileSnapshotState(TypedDict, total=False):
    course_id: str
    user_id: str
    top_n: int
    knowledge_unit_states: list[dict[str, object]]
    weak_knowledge_unit_count: int
    course_profile: dict[str, object] | None
    user_profile: dict[str, object] | None
    report_generated: bool
    validate_snapshot_ms: int
    load_mastery_overview_ms: int
    build_course_profile_ms: int
    build_user_profile_ms: int
    workflow_elapsed_ms: int
    error: str | None


__all__ = ["ProfileSnapshotState"]
