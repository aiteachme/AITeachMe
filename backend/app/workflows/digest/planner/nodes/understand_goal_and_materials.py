"""Reuse deterministic material context before composing a plan."""

from __future__ import annotations

import structlog

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_course_name, compose_planning_note
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _course_for_prompt(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    return _resolve_course_name(
        state["course_id"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


def _clean_items(values: object, *, limit: int = 6) -> list[str]:
    items = values if isinstance(values, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for value in items:
        text = " ".join(str(value or "").split()).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _build_planning_note(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    user_prompt = " ".join(str(state.get("user_prompt") or "").split()).strip()
    mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
    goal = user_prompt or f"围绕{_course_for_prompt(state)}建立可执行学习路径"
    pace = "紧凑冲刺" if str(mode) == "sprint" else "系统学习"
    return f"学习目标：{goal}。规划节奏：{pace}；方案将直接以用户目标和已解析资料为边界。"


def _build_material_note(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    sources = list(material_context.source_documents or [])
    filenames = _clean_items([item.filename for item in sources], limit=4)
    topics = _clean_items(
        [
            *list(material_context.material_hints.chapter_candidates or []),
            *list(material_context.learning_domain_profile.key_topics or []),
            *list(material_context.learning_domain_profile.knowledge_domain_hints or []),
        ],
        limit=6,
    )
    if not sources:
        return "当前没有已解析本地资料；方案将严格依据用户目标组织，并明确资料不足处。"
    parts = [f"已解析 {len(sources)} 份资料"]
    if filenames:
        parts.append("来源包括：" + "、".join(filenames))
    if topics:
        parts.append("资料主题集中在：" + "、".join(topics))
    parts.append("后续章节只从这些资料和用户目标确定范围")
    return "；".join(parts) + "。"


def build_understand_goal_and_materials_node(*, context: WorkflowContext):
    """Build planning context directly from already prepared material facts."""

    del context

    async def understand_goal_and_materials_node(state: BuildPlannerState) -> dict:
        if state.get("error"):
            return {}
        if str(state.get("planner_operation") or "") != "create":
            latest_plan = dict(state.get("latest_plan") or {})
            planning_note = compose_planning_note(latest_plan.get("planning_note"))
            return {
                "planning_note": planning_note,
                "material_note": "",
            }

        await emit_planner_event(
            state,
            event="planner.analysis.started",
            detail="正在复用已解析的学习目标和资料边界。",
        )
        planning_note = _build_planning_note(state)
        material_note = _build_material_note(state)
        await emit_planner_token(state, planning_note)
        await emit_planner_event(
            state,
            event="planner.analysis.ready",
            detail="学习目标和资料边界已就绪，开始生成正式方案。",
            payload={"planning_note": compose_planning_note(planning_note, material_note)},
        )
        logger.info(
            "planner_material_context_reused",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
            source_count=len(state["material_context"].source_documents),
        )
        return {"planning_note": planning_note, "material_note": material_note}

    return understand_goal_and_materials_node


__all__ = ["build_understand_goal_and_materials_node"]
