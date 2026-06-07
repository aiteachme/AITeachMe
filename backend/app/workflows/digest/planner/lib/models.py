"""Small planner-only data contracts."""

from __future__ import annotations

from pydantic import BaseModel


class PlannerIntent(BaseModel):
    """First-pass user intent streamed before the final plan."""

    intent: str = ""


class PlannerMaterialSummary(BaseModel):
    """Short subject/material summary from the selected learning materials."""

    summary: str = ""


class PlannerCourseIdentity(BaseModel):
    """Course display metadata generated in one model call."""

    course_name: str = ""
    course_icon: str = ""


def build_empty_planner_intent() -> PlannerIntent:
    return PlannerIntent(intent="")


__all__ = [
    "PlannerCourseIdentity",
    "PlannerIntent",
    "PlannerMaterialSummary",
    "build_empty_planner_intent",
]
