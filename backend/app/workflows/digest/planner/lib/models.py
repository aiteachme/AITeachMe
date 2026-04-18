"""Small planner-only data contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlannerBrief(BaseModel):
    """User-visible planning sketch streamed before the final plan."""

    markdown: str = ""


class PlanIntent(BaseModel):
    """Internal planning intent used to steer the final composer."""

    plan_intent: str = ""
    plan_queries: list[str] = Field(default_factory=list)


def build_empty_planner_brief() -> PlannerBrief:
    return PlannerBrief(markdown="")


__all__ = [
    "PlanIntent",
    "PlannerBrief",
    "build_empty_planner_brief",
]
