"""Planner models and fallback helpers."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from app.shared.infra.config import get_settings
from app.workflows.digest.shared.models import SharedInputs


class PlannerChapterPlan(BaseModel):
    chapter_index: int
    title: str
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    writing_instructions: str = ""
    media_hints: dict[str, list[str]] = Field(
        default_factory=lambda: {"images": [], "mermaid": [], "interactive": []}
    )


class BuildPlannerDraft(BaseModel):
    subject: str
    user_goal: str
    digest_mode: str = "systematic"
    tone: str = "encouraging"
    chapter_plan: list[PlannerChapterPlan] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    build_constraints: dict[str, Any] = Field(default_factory=dict)
    plan_summary: str = ""


def _collect_topic_hints(shared_inputs: SharedInputs, *, limit: int = 8) -> list[str]:
    raw_topics = [
        *shared_inputs.subject_profile.key_topics,
        *shared_inputs.fast_hints.chapter_candidates,
    ]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_topics:
        topic = str(item or "").strip()
        if not topic or topic in seen:
            continue
        seen.add(topic)
        cleaned.append(topic)
        if len(cleaned) >= limit:
            break
    return cleaned


def _build_sprint_fallback_plan(
    *,
    subject: str,
    user_goal: str,
    tone: str,
    shared_inputs: SharedInputs,
) -> BuildPlannerDraft:
    settings = get_settings()
    topics = _collect_topic_hints(shared_inputs, limit=4)
    focus_topic = topics[0] if topics else (shared_inputs.subject_profile.subject_name or subject)
    chapter_specs = [
        (
            "概念破冰",
            "先用生活化视角把最难啃的概念讲明白，让学生快速建立第一层直觉。",
            ["通俗类比", "核心概念", "知识关系"],
            [
                f"{subject} {focus_topic} 通俗理解",
                f"{subject} {focus_topic} 核心概念 梳理",
            ],
            "必须先用生活例子或考场场景引入，再解释核心概念之间的关系，并加入一个 Mermaid 速记图占位符。",
            {
                "images": [f"{focus_topic} 的直观示意图"],
                "mermaid": [f"{focus_topic} 的概念速记图"],
                "interactive": [],
            },
        ),
        (
            "公式武器库",
            "把最关键的公式、适用条件和大白话翻译整理成冲刺可背的工具箱。",
            ["核心公式", "适用条件", "公式翻译"],
            [
                f"{subject} {focus_topic} 公式 总结",
                f"{subject} {focus_topic} 常用公式 条件",
            ],
            "每个公式后面都要补一句大白话解释，并强调什么时候能用、什么时候最容易用错。",
            {
                "images": [f"{focus_topic} 的公式使用示意图"],
                "mermaid": [f"{focus_topic} 公式之间的关系图"],
                "interactive": [],
            },
        ),
        (
            "真题实战",
            "围绕高频题型拆步骤、讲思路、补变式，帮助学生形成考场操作感。",
            ["典型题型", "步骤推导", "变式提醒"],
            [
                f"{subject} {focus_topic} 典型例题 解析",
                f"{subject} {focus_topic} 真题 解法",
            ],
            "必须给出步骤化拆解，突出题型抓手、关键转折点和一题多变的提醒。",
            {
                "images": [f"{focus_topic} 典型题型的步骤图"],
                "mermaid": [f"{focus_topic} 解题流程图"],
                "interactive": [],
            },
        ),
        (
            "防坑指南",
            "汇总最常见的误区、混淆点和考前检查清单，帮助学生最后兜底。",
            ["易错点", "混淆概念", "考前清单"],
            [
                f"{subject} {focus_topic} 易错点 总结",
                f"{subject} {focus_topic} 常见陷阱 对比",
            ],
            "要明确列出最常见的错法、为什么会错，以及考前一分钟应该回看什么。",
            {
                "images": [f"{focus_topic} 常见错误示意图"],
                "mermaid": [f"{focus_topic} 易错点对照图"],
                "interactive": [],
            },
        ),
    ]

    chapter_plan = [
        PlannerChapterPlan(
            chapter_index=index,
            title=title,
            objective=objective,
            required_elements=required_elements,
            search_queries=queries,
            writing_instructions=writing_instructions,
            media_hints=media_hints,
        )
        for index, (title, objective, required_elements, queries, writing_instructions, media_hints) in enumerate(
            chapter_specs,
            start=1,
        )
    ]
    research_queries = [query for chapter in chapter_plan for query in chapter.search_queries]
    return BuildPlannerDraft(
        subject=subject,
        user_goal=user_goal,
        digest_mode="sprint",
        tone=tone,
        chapter_plan=chapter_plan,
        research_queries=list(dict.fromkeys(research_queries)),
        media_plan={
            "enable_mermaid": settings.enable_mermaid_generation,
            "enable_images": settings.enable_image_generation,
            "enable_interactive_html": False,
        },
        build_constraints={
            "fixed_chapter_count": 4,
            "include_exercises": True,
            "include_sources": True,
            "math_mode": shared_inputs.subject_profile.has_heavy_formulas,
            "target_length": "3000-5000字",
        },
        plan_summary=f"围绕 {subject} 生成一份冲刺型知识文档，固定为 4 章：概念破冰、公式武器库、真题实战、防坑指南。",
    )


def _build_systematic_middle_titles(topic_hints: list[str], *, target_count: int) -> list[str]:
    fallback_titles = [
        "核心定义与符号",
        "关键结构与公式",
        "推理与证明思路",
        "应用与例题",
        "易混概念与边界条件",
        "方法串联与综合理解",
        "典型场景与扩展问题",
        "知识回看与迁移练习",
    ]
    if topic_hints:
        hinted_titles = [f"{topic}：核心定义与方法" for topic in topic_hints[:target_count]]
        if len(hinted_titles) >= target_count:
            return hinted_titles[:target_count]
        remaining = target_count - len(hinted_titles)
        return hinted_titles + fallback_titles[:remaining]
    return fallback_titles[:target_count]


def _build_systematic_fallback_plan(
    *,
    subject: str,
    user_goal: str,
    tone: str,
    shared_inputs: SharedInputs,
) -> BuildPlannerDraft:
    settings = get_settings()
    topic_hints = _collect_topic_hints(shared_inputs, limit=8)
    target_count = min(
        settings.planner_max_chapters,
        max(settings.planner_min_chapters, math.ceil(max(1, len(topic_hints)) / 1.5) + 2),
    )
    middle_count = max(4, target_count - 2)
    middle_titles = _build_systematic_middle_titles(topic_hints, target_count=middle_count)
    titles = ["全景导论", *middle_titles, "总结与延展"]
    titles = titles[:target_count]

    chapter_plan: list[PlannerChapterPlan] = []
    all_queries: list[str] = []
    overall_topic = "、".join(topic_hints[:4]) if topic_hints else (shared_inputs.subject_profile.subject_name or subject)
    last_index = len(titles)

    for index, title in enumerate(titles, start=1):
        if index == 1:
            objective = "先建立整个主题的知识全景、学习顺序和章节关系，再进入细节。"
            required_elements = ["知识全景", "学习路径", "概念关系图"]
            queries = [
                f"{subject} {overall_topic} 知识框架",
                f"{subject} {overall_topic} 学习路线",
            ]
            writing_instructions = "这一章必须是全景导论，先交代整体学习路径，再给出全局脉络图，并说明后续章节分别解决什么问题。"
            media_hints = {
                "images": [f"{overall_topic} 的整体结构示意图"],
                "mermaid": [f"{overall_topic} 的全景知识脉络图"],
                "interactive": [],
            }
        elif index == last_index:
            objective = "回收整份文档的主线，串起核心知识，并给出进一步深入学习的路径。"
            required_elements = ["全局串联", "常见误区", "进阶路径"]
            queries = [
                f"{subject} {overall_topic} 总结 复习",
                f"{subject} {overall_topic} 进阶 学习路径",
            ]
            writing_instructions = "这一章必须承担总结与延展的职责，回顾全文主线，并给出后续进阶建议。"
            media_hints = {
                "images": [f"{overall_topic} 的进阶学习路线图"],
                "mermaid": [f"{overall_topic} 的知识回收图"],
                "interactive": [],
            }
        else:
            focus_topic = title.split("：", 1)[0].strip() or title
            objective = f"围绕“{focus_topic}”建立定义、公式、推理、应用之间的系统理解。"
            required_elements = ["前置知识", "核心定义", "推理或证明", "应用示例"]
            queries = [
                f"{subject} {focus_topic} 定义 公式",
                f"{subject} {focus_topic} 例题 应用",
            ]
            writing_instructions = "本章要按“前置知识 -> 动机引入 -> 核心定义与定理 -> 推理与应用 -> 本章要点”的结构展开。"
            media_hints = {
                "images": [f"{focus_topic} 的解释性配图"],
                "mermaid": [f"{focus_topic} 在整体知识中的位置图"],
                "interactive": [],
            }

        all_queries.extend(queries)
        chapter_plan.append(
            PlannerChapterPlan(
                chapter_index=index,
                title=title,
                objective=objective,
                required_elements=required_elements,
                search_queries=queries,
                writing_instructions=writing_instructions,
                media_hints=media_hints,
            )
        )

    return BuildPlannerDraft(
        subject=subject,
        user_goal=user_goal,
        digest_mode="systematic",
        tone=tone,
        chapter_plan=chapter_plan,
        research_queries=list(dict.fromkeys(all_queries)),
        media_plan={
            "enable_mermaid": settings.enable_mermaid_generation,
            "enable_images": settings.enable_image_generation,
            "enable_interactive_html": False,
        },
        build_constraints={
            "min_chapters": 6,
            "max_chapters": 10,
            "include_exercises": True,
            "include_sources": True,
            "math_mode": shared_inputs.subject_profile.has_heavy_formulas,
            "target_length": "10000-15000字",
        },
        plan_summary=f"围绕 {subject} 生成一份系统型知识文档，首章为全景导论，末章为总结与延展，中间章节按主题逐层展开。",
    )


def build_fallback_plan(
    *,
    subject: str,
    user_goal: str,
    digest_mode: str,
    tone: str,
    shared_inputs: SharedInputs,
) -> BuildPlannerDraft:
    normalized_mode = (digest_mode or "systematic").strip().lower()
    if normalized_mode == "sprint":
        return _build_sprint_fallback_plan(
            subject=subject,
            user_goal=user_goal,
            tone=tone,
            shared_inputs=shared_inputs,
        )
    return _build_systematic_fallback_plan(
        subject=subject,
        user_goal=user_goal,
        tone=tone,
        shared_inputs=shared_inputs,
    )


__all__ = ["BuildPlannerDraft", "PlannerChapterPlan", "build_fallback_plan"]
