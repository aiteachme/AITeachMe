"""Small planner-only data contracts.

These models are deliberately flatter than the final build-plan contract.
They are short-lived artifacts used to make the planner trace readable:

- ``PlannerBrief``: user-visible planning sketch from the streaming model.
- ``LearningIntent``: compact goal classification.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.workflows.digest.common.models import DigestMaterialContext


class PlannerBrief(BaseModel):
    """Visible planning sketch and its parsed signals."""

    markdown: str = ""
    focus_points: list[str] = Field(default_factory=list)
    outline_items: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class LearningIntent(BaseModel):
    """Minimal user-goal interpretation for planning."""

    goal_type: str = "knowledge_doc"
    audience: str = "当前学习者"
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)
    focus_concepts: list[str] = Field(default_factory=list)
    confidence: float = 0.6


def material_topic_hints(material_context: DigestMaterialContext) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    for item in [
        *material_context.learning_domain_profile.key_topics,
        *material_context.material_hints.chapter_candidates,
    ]:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        hints.append(text)
    return hints


def build_empty_planner_brief() -> PlannerBrief:
    return PlannerBrief(
        markdown="",
        clarifying_questions=["请补充更明确的学习目标、章节范围或题型偏好。"],
    )


__all__ = [
    "LearningIntent",
    "PlannerBrief",
    "build_empty_planner_brief",
    "material_topic_hints",
]
