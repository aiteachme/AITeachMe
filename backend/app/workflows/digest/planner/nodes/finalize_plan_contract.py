"""Finalize and normalize Planner V3 plan contract."""

from __future__ import annotations

import re

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.plans import (
    BuildPlannerDraft,
    _dedupe_chapter_plan_titles,
    _resolve_subject_display_name,
    normalize_planner_draft,
)
from app.workflows.digest.planner.lib.research_probe import PlanSketch
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.shared.contracts import resolve_digest_course_type, resolve_planner_retrieval_profile

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


def _prefer_plan_sketch_titles(
    draft: BuildPlannerDraft,
    *,
    plan_sketch: PlanSketch,
    user_goal: str,
    subject_display_name: str,
) -> BuildPlannerDraft:
    if not plan_sketch.provisional_chapters:
        return draft
    next_plan = []
    for index, chapter in enumerate(draft.chapter_plan):
        sketch_title = (
            str(plan_sketch.provisional_chapters[index]).strip()
            if index < len(plan_sketch.provisional_chapters)
            else ""
        )
        current_title = str(chapter.title or "").strip()
        if sketch_title and _looks_generic_title(current_title, user_goal=user_goal):
            next_plan.append(chapter.model_copy(update={"title": sketch_title}))
        else:
            next_plan.append(chapter)
    return draft.model_copy(
        update={
            "chapter_plan": _dedupe_chapter_plan_titles(
                next_plan,
                subject_display_name=subject_display_name,
            )
        }
    )


def _prefer_plan_sketch_queries(
    draft: BuildPlannerDraft,
    *,
    plan_sketch: PlanSketch,
) -> BuildPlannerDraft:
    if not plan_sketch.research_tasks:
        return draft
    existing = list(draft.research_queries)
    if existing and not all(_looks_fallback_query(query) for query in existing):
        return draft
    return draft.model_copy(update={"research_queries": list(plan_sketch.research_tasks[:8])})


def build_finalize_plan_contract_node(*, context: WorkflowContext):
    async def finalize_plan_contract_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        plan_sketch = PlanSketch.model_validate(state.get("plan_sketch") or {})
        digest_mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
        tone = state.get("tone") or "encouraging"
        draft = normalize_planner_draft(
            state.get("build_plan_contract") or {},
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            requested_digest_mode=digest_mode,
            requested_tone=tone,
            selected_skillpacks=list(state.get("selected_skillpacks") or []),
            shared_inputs=material_context,
            latest_plan=state.get("latest_plan"),
        )
        display_subject = _resolve_subject_display_name(
            state["subject"],
            shared_inputs=material_context,
            user_goal=state.get("user_goal") or "",
        )
        draft = _prefer_plan_sketch_titles(
            draft,
            plan_sketch=plan_sketch,
            user_goal=state.get("user_goal") or "",
            subject_display_name=display_subject,
        )
        draft = _prefer_plan_sketch_queries(
            draft,
            plan_sketch=plan_sketch,
        )
        draft = draft.model_copy(
            update={
                "chapter_plan": _dedupe_chapter_plan_titles(
                    list(draft.chapter_plan),
                    subject_display_name=display_subject,
                )
            }
        )
        plan = draft.model_dump(mode="json")
        await emit_planner_event(
            state,
            event="planner.plan.ready",
            detail="构建方案已生成，可以确认或继续修改。",
            payload={
                "chapter_count": len(draft.chapter_plan),
                "digest_mode": draft.digest_mode,
            },
        )
        return {
            "plan": plan,
            "plan_summary": draft.plan_summary,
            "digest_mode": draft.digest_mode,
            "course_type": resolve_digest_course_type(draft.digest_mode),
            "retrieval_profile": resolve_planner_retrieval_profile(),
            "teaching_action": str(state.get("teaching_action") or "plan_course"),
            "tone": draft.tone,
            "selected_skillpacks": list(draft.selected_skillpacks),
            "planner_generation_mode": state.get("planner_generation_mode") or "deep_research_v3",
        }

    return finalize_plan_contract_node


__all__ = ["build_finalize_plan_contract_node"]
