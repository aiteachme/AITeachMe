"""Planner lane-local models and fallback builders."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.workflows.digest.planner.lib.plans import BuildPlannerDraft
from app.workflows.digest.common.models import DigestMaterialContext


class PlannerQuery(BaseModel):
    query: str = ""
    purpose: str = ""
    expected_signal: str = ""
    source_scope: str = "local"


class ResearchProbePlan(BaseModel):
    source_policy: str = "all_available"
    local_queries: list[PlannerQuery] = Field(default_factory=list)
    web_queries: list[PlannerQuery] = Field(default_factory=list)


class PlanSketch(BaseModel):
    title: str = ""
    summary: str = ""
    research_tasks: list[str] = Field(default_factory=list)
    provisional_chapters: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_clarifications: list[str] = Field(default_factory=list)
    raw_text: str = ""


class LearningIntentProfile(BaseModel):
    goal_type: str = "knowledge_doc"
    target_audience: str = "learner"
    success_criteria: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    source_policy: str = "all_available"
    research_probe_plan: ResearchProbePlan = Field(default_factory=ResearchProbePlan)
    clarifying_questions: list[str] = Field(default_factory=list)
    confidence: float = 0.6


class PlannerSelectedSource(BaseModel):
    title: str = ""
    url: str = ""
    source_type: str = "local"
    reason: str = ""
    target_chapters: list[str] = Field(default_factory=list)
    should_open: bool = True
    snippet: str = ""


class PlannerOpenedSource(BaseModel):
    title: str = ""
    url: str = ""
    source_type: str = "local"
    content_preview: str = ""
    target_chapters: list[str] = Field(default_factory=list)


class ChapterEvidenceHint(BaseModel):
    chapter_hint: str = ""
    evidence_summary: str = ""
    source_titles: list[str] = Field(default_factory=list)


class EvidenceBrief(BaseModel):
    selected_sources: list[PlannerSelectedSource] = Field(default_factory=list)
    opened_sources: list[PlannerOpenedSource] = Field(default_factory=list)
    concept_briefing: str = ""
    core_concepts: list[str] = Field(default_factory=list)
    chapter_evidence_hints: list[ChapterEvidenceHint] = Field(default_factory=list)
    gap_notes: list[str] = Field(default_factory=list)
    source_quality_summary: dict[str, int] = Field(default_factory=dict)
    local_hit_count: int = 0
    web_hit_count: int = 0


def material_topic_hints(material_context: DigestMaterialContext, *, limit: int = 8) -> list[str]:
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
        if len(hints) >= limit:
            break
    return hints


def build_default_research_probe_plan(
    *,
    material_context: DigestMaterialContext,
    user_goal: str,
) -> ResearchProbePlan:
    topic_hints = material_topic_hints(material_context, limit=4)
    base = str(user_goal or "").strip() or "当前学习主题"
    queries = [
        PlannerQuery(
            query=f"{topic} 核心概念 学习重点",
            purpose=f"用本地资料和外部资料一起校准 {topic} 的知识边界。",
            expected_signal="资料命中、权威定义、学习路径、方法结构或常见误区",
            source_scope="all",
        )
        for topic in topic_hints
    ]
    if not queries:
        queries = [
            PlannerQuery(
                query=f"{base} 基础概念 知识框架",
                purpose="用本地资料和外部资料一起校准最基础的学习框架。",
                expected_signal="资料命中、核心概念、章节结构或权威定义",
                source_scope="all",
            )
        ]
    return ResearchProbePlan(source_policy="all_available", local_queries=queries[:4], web_queries=queries[:4])


def build_default_intent_profile(
    *,
    material_context: DigestMaterialContext,
    user_goal: str,
    digest_mode: str,
) -> LearningIntentProfile:
    normalized_mode = str(digest_mode or "").strip().lower()
    goal_type = "exam_sprint" if normalized_mode == "sprint" else "systematic_learning"
    probe_plan = build_default_research_probe_plan(
        material_context=material_context,
        user_goal=user_goal,
    )
    return LearningIntentProfile(
        goal_type=goal_type,
        target_audience="当前学习者",
        success_criteria=["形成可确认的知识文档大纲", "明确每章检索与写作目标"],
        constraints={"digest_mode": normalized_mode or "systematic"},
        source_policy="all_available",
        research_probe_plan=probe_plan,
        confidence=0.55,
    )


def build_fallback_plan_sketch(draft: BuildPlannerDraft) -> PlanSketch:
    research_tasks = list(draft.research_queries[:8])
    provisional_chapters = [chapter.title for chapter in draft.chapter_plan]
    assumptions = ["优先依据用户目标和已上传资料生成可确认大纲。"]
    missing_clarifications = ["如需更聚焦，可继续补充章节方向、难度或题型偏好。"]
    raw_text = "\n".join(
        [
            "# 思考过程",
            "",
            f"> 我会先按 {draft.digest_mode} 模式理解资料边界，再提炼可执行的大纲。",
            "",
            "## 思考重点",
            *[f"{index}. {item}" for index, item in enumerate(research_tasks, start=1)],
            "",
            "## 计划大纲",
            *[f"{index}. {item}" for index, item in enumerate(provisional_chapters, start=1)],
            "",
            "## 规划假设",
            *[f"- {item}" for item in assumptions],
            "",
            "## 待确认点",
            *[f"- {item}" for item in missing_clarifications],
        ]
    ).strip()
    return PlanSketch(
        title=f"{draft.subject}学习规划",
        summary=draft.plan_summary,
        research_tasks=research_tasks,
        provisional_chapters=provisional_chapters,
        assumptions=assumptions,
        missing_clarifications=missing_clarifications,
        raw_text=raw_text,
    )


__all__ = [
    "ChapterEvidenceHint",
    "EvidenceBrief",
    "LearningIntentProfile",
    "PlanSketch",
    "PlannerOpenedSource",
    "PlannerQuery",
    "PlannerSelectedSource",
    "ResearchProbePlan",
    "build_default_intent_profile",
    "build_default_research_probe_plan",
    "build_fallback_plan_sketch",
    "material_topic_hints",
]
