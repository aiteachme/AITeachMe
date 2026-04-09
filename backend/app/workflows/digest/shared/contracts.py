"""Shared build-contract helpers for digest planner and docgen lanes."""

from __future__ import annotations


DEFAULT_COURSE_TYPE = "systematic"
SPRINT_COURSE_TYPE = "sprint"
PLANNER_RETRIEVAL_PROFILE = "planner_grounding"


def resolve_digest_course_type(digest_mode: str | None) -> str:
    """Resolve the normalized course type from the requested digest mode."""

    normalized = str(digest_mode or "").strip().lower()
    if normalized == SPRINT_COURSE_TYPE:
        return SPRINT_COURSE_TYPE
    return DEFAULT_COURSE_TYPE


def resolve_digest_retrieval_profile(digest_mode: str | None) -> str:
    """Resolve the retrieval profile that should be used for doc generation."""

    course_type = resolve_digest_course_type(digest_mode)
    if course_type == SPRINT_COURSE_TYPE:
        return "docgen_sprint"
    return "docgen_systematic"


def resolve_planner_retrieval_profile() -> str:
    """Resolve the retrieval profile used by the planner grounding lane."""

    return PLANNER_RETRIEVAL_PROFILE


def resolve_teaching_action(action: str | None, *, fallback: str) -> str:
    """Normalize teaching-action labels so tracing metadata stays stable."""

    normalized = str(action or "").strip()
    return normalized or fallback


__all__ = [
    "DEFAULT_COURSE_TYPE",
    "PLANNER_RETRIEVAL_PROFILE",
    "SPRINT_COURSE_TYPE",
    "resolve_digest_course_type",
    "resolve_digest_retrieval_profile",
    "resolve_planner_retrieval_profile",
    "resolve_teaching_action",
]
