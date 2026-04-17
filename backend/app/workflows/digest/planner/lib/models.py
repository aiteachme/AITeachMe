"""Small planner-only data contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlannerBrief(BaseModel):
    """User-visible planning sketch streamed before the final plan."""

    markdown: str = ""


class LearningIntent(BaseModel):
    """Compact user-goal interpretation for planning."""

    goal_type: str = "knowledge_doc"
    audience: str = "当前学习者"
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    focus_concepts: list[str] = Field(default_factory=list)


def build_empty_planner_brief() -> PlannerBrief:
    return PlannerBrief(markdown="")


__all__ = [
    "LearningIntent",
    "PlannerBrief",
    "build_empty_planner_brief",
]
