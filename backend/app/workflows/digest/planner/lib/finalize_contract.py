"""Final planner contract cleanup helpers."""

from __future__ import annotations

import re

from app.workflows.digest.planner.lib.plans import BuildPlannerDraft, _dedupe_chapter_plan_titles
from app.workflows.digest.planner.lib.models import PlannerBrief

_GENERIC_TITLE_MARKERS = (
    "当前主题",
    "学习规划",
    "知识文档",
    "系统课",
    "冲刺课",
    "专题",
    "根据我上传资料",
    "介绍下",
)
_GENERIC_QUERY_SUFFIXES = (
    "核心概念",
    "通俗理解",
    "考点梳理",
    "公式总结",
    "方法技巧",
    "使用条件",
    "典型题型",
    "例题解析",
    "学习路径",
    "知识框架",
    "前置知识",
)


def _looks_generic_title(title: str, *, user_goal: str) -> bool:
    cleaned = str(title or "").strip()
    if not cleaned:
        return True
    if any(marker in cleaned for marker in _GENERIC_TITLE_MARKERS):
        return True
    if len(cleaned) > 26:
        return True
    goal = re.sub(r"\s+", "", str(user_goal or ""))
    compact = re.sub(r"\s+", "", cleaned)
    if goal and len(goal) >= 8 and goal in compact:
        return True
    if re.match(r"^(?:Part|章节|第\s*\d+\s*章)", cleaned, re.IGNORECASE):
        return True
    return False


def _looks_fallback_query(query: str) -> bool:
    cleaned = str(query or "").strip()
    if not cleaned:
        return True
    if any(cleaned.endswith(suffix) for suffix in _GENERIC_QUERY_SUFFIXES):
        return True
    if cleaned.count("计算机基础知识") >= 2:
        return True
    if re.match(r"^[\u4e00-\u9fffA-Za-z0-9\s]+$", cleaned) and len(cleaned) <= 24:
        return False
    return False


def apply_planner_brief_preferences(
    draft: BuildPlannerDraft,
    *,
    planner_brief: PlannerBrief,
    user_goal: str,
    subject_display_name: str,
) -> BuildPlannerDraft:
    if planner_brief.outline_items:
        next_plan = []
        for index, chapter in enumerate(draft.chapter_plan):
            sketch_title = (
                str(planner_brief.outline_items[index]).strip()
                if index < len(planner_brief.outline_items)
                else ""
            )
            current_title = str(chapter.title or "").strip()
            if sketch_title and _looks_generic_title(current_title, user_goal=user_goal):
                next_plan.append(chapter.model_copy(update={"title": sketch_title}))
            else:
                next_plan.append(chapter)
        draft = draft.model_copy(
            update={
                "chapter_plan": _dedupe_chapter_plan_titles(
                    next_plan,
                    subject_display_name=subject_display_name,
                )
            }
        )

    if planner_brief.focus_points:
        existing = list(draft.research_queries)
        if not existing or all(_looks_fallback_query(query) for query in existing):
            draft = draft.model_copy(update={"research_queries": list(planner_brief.focus_points[:8])})

    return draft.model_copy(
        update={
            "chapter_plan": _dedupe_chapter_plan_titles(
                list(draft.chapter_plan),
                subject_display_name=subject_display_name,
            )
        }
    )


__all__ = ["apply_planner_brief_preferences"]
