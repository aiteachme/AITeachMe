"""Small planner-only data contracts.

These models are deliberately flatter than the final build-plan contract.
They are short-lived artifacts used to make the planner trace readable:

- ``PlannerBrief``: user-visible planning sketch from the streaming model.
- ``LearningIntent``: compact goal classification.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.plans import BuildPlannerDraft


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


def build_default_intent(
    *,
    digest_mode: str,
) -> LearningIntent:
    normalized_mode = str(digest_mode or "").strip().lower()
    goal_type = "exam_sprint" if normalized_mode == "sprint" else "systematic_learning"
    return LearningIntent(
        goal_type=goal_type,
        audience="当前学习者",
        success_criteria=["形成可确认的知识文档大纲", "明确每章写作重点"],
        constraints=[f"digest_mode={normalized_mode or 'systematic'}"],
        confidence=0.55,
    )


def build_fallback_planner_brief(draft: BuildPlannerDraft) -> PlannerBrief:
    focus_points = list(draft.research_queries)
    outline_items = [chapter.title for chapter in draft.chapter_plan]
    fallback_focus = focus_points or ["优先依据用户目标和已上传资料生成可确认大纲"]
    fallback_outline = outline_items or ["继续补充章节方向、难度或题型偏好"]
    markdown = "\n".join(
        [
            "我会先按用户目标和资料主题收敛一版可确认规划。",
            "重点线索：" + "；".join(fallback_focus) + "。",
            "暂定方向：" + "；".join(fallback_outline) + "。",
        ]
    ).strip()
    return PlannerBrief(
        markdown=markdown,
        focus_points=focus_points,
        outline_items=outline_items,
        clarifying_questions=["如需更聚焦，可继续补充章节方向、难度或题型偏好。"],
    )


__all__ = [
    "LearningIntent",
    "PlannerBrief",
    "build_default_intent",
    "build_fallback_planner_brief",
    "material_topic_hints",
]
