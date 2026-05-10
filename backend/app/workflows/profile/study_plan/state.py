"""State contract for the Profile study-plan lane.

This lane builds short actionable learning plans from existing profile
signals. It does not replace Digest Planner, which plans source-material
digestion and knowledge-document structure.
"""

from __future__ import annotations

from typing import TypedDict


class ProfileStudyPlanState(TypedDict, total=False):
    course_id: str
    user_id: str
    course_profile: dict[str, object] | None
    user_profile: dict[str, object] | None
    study_plan: list[dict[str, object]]
    load_profile_context_ms: int
    build_study_plan_ms: int
    workflow_elapsed_ms: int
    error: str | None


__all__ = ["ProfileStudyPlanState"]
