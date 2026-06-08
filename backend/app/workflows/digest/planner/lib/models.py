"""Small planner-only data contracts."""

from __future__ import annotations

from pydantic import BaseModel


class PlannerMaterialNote(BaseModel):
    """Short subject/material note from the selected learning materials."""

    material_note: str = ""


class PlannerCourseIdentity(BaseModel):
    """Course display metadata generated in one model call."""

    course_name: str = ""
    course_icon: str = ""

__all__ = [
    "PlannerCourseIdentity",
    "PlannerMaterialNote",
]
