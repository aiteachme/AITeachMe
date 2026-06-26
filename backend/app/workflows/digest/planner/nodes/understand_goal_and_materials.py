"""Understand the learning goal and material scope before composing a plan."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback, run_llm_tasks
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.models import PlannerMaterialNote
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_course_name, compose_planning_note, planner_mode_label
from app.workflows.digest.planner.prompts.context import render_material_digest, render_material_overview
from app.workflows.digest.planner.prompts.goal_materials import (
    build_material_note_messages,
    build_stream_planning_note_prompt,
)
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _compact_text(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _course_for_prompt(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    return _resolve_course_name(
        state["course_id"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


def _fallback_planning_note(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    user_prompt = _compact_text(state.get("user_prompt") or "", limit=220)
    digest_mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
    material_digest = _compact_text(render_material_digest(material_context), limit=260)
    lines = [
        f"已根据当前输入生成初步规划判断，采用{planner_mode_label(digest_mode)}组织学习路径。",
    ]
    if user_prompt:
        lines.append(f"学习目标：{user_prompt}")
    if material_digest:
        lines.append(f"资料线索：{material_digest}")
    lines.append("后续方案会先给出可调整的章节边界；如资料摘要不完整，需在正式生成前继续以用户反馈校准重点。")
    return "\n".join(lines)


def _fallback_material_note(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    overview = _compact_text(render_material_overview(material_context), limit=300)
    digest = _compact_text(render_material_digest(material_context), limit=240)
    lines = ["资料边界：本轮使用已上传资料的解析摘要、文件名和用户目标进行规划。"]
    if overview:
        lines.append(f"资料概况：{overview}")
    if digest:
        lines.append(f"摘要线索：{digest}")
    return "\n".join(lines)


async def _run_understanding_task(
    state: BuildPlannerState,
    *,
    task_name: str,
    event: str,
    payload_key: str,
    fallback_detail: str,
    factory: Callable[[], Awaitable[str]],
    fallback_factory: Callable[[BuildPlannerState], str],
) -> str:
    try:
        return await factory()
    except Exception as exc:
        fallback_text = fallback_factory(state)
        logger.warning(
            "planner_understanding_task_fallback_used",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id") or "",
            task_name=task_name,
            error_type=type(exc).__name__,
            error=str(exc),
            fallback_chars=len(fallback_text),
        )
        await emit_planner_event(
            state,
            event=event,
            detail=fallback_detail,
            payload={
                payload_key: fallback_text,
                "fallback_reason": type(exc).__name__,
            },
        )
        return fallback_text


async def _stream_planning_note(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    prompt = build_stream_planning_note_prompt(
        course_name=_course_for_prompt(state),
        user_prompt=state.get("user_prompt") or "",
        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
        material_context=material_context,
        message_history=list(state.get("message_history", [])),
    )
    tokens: list[str] = []
    started_at = time.monotonic()
    first_token_ms: int | None = None
    await emit_planner_event(state, event="planner.planning_note.started", detail="正在识别学习意图和规划边界。")
    stream = acompletion_stream(
        [{"role": "user", "content": prompt}],
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.STREAM_PLANNING_NOTE,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="流式生成 planning_note",
        ),
    )
    async for token in stream:
        if first_token_ms is None:
            first_token_ms = int((time.monotonic() - started_at) * 1000)
        tokens.append(token)
        await emit_planner_token(state, token)
    text = "".join(tokens).strip()
    logger.info(
        "planner_planning_note_stream_completed",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id") or "",
        first_token_ms=first_token_ms,
        planning_note_chars=len(text),
    )
    if not text:
        raise ValueError("planner planning_note stream returned empty text")
    await emit_planner_event(
        state,
        event="planner.planning_note.ready",
        detail="规划判断已生成，准备结合资料边界生成方案。",
        payload={"planning_note": text},
    )
    return text


async def _summarize_materials(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    await emit_planner_event(state, event="planner.material_note.started", detail="正在整理资料边界和学科情况。")
    result = await acompletion_with_fallback(
        build_material_note_messages(
            course_name=_course_for_prompt(state),
            user_prompt=state.get("user_prompt") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            material_context=material_context,
        ),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.SUMMARIZE_MATERIALS,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="生成 material_note",
        ),
        response_model=PlannerMaterialNote,
    )
    material_note = result.material_note.strip() if isinstance(result, PlannerMaterialNote) else PlannerMaterialNote.model_validate(result).material_note.strip()
    if not material_note:
        raise ValueError("planner material_note returned empty text")
    await emit_planner_event(
        state,
        event="planner.material_note.ready",
        detail="资料边界已整理。",
        payload={"material_note": material_note},
    )
    return material_note


def build_understand_goal_and_materials_node(*, context: WorkflowContext):
    """Build the planning note + material note fan-out node."""

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

        logger.info(
            "planner_planning_note_node_started",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
        )
        planning_note, material_note = await run_llm_tasks(
            [
                lambda: _run_understanding_task(
                    state,
                    task_name="planning_note",
                    event="planner.planning_note.fallback",
                    payload_key="planning_note",
                    fallback_detail="规划判断模型响应较慢，已先用当前资料摘要生成可继续推进的初步判断。",
                    factory=lambda: _stream_planning_note(state),
                    fallback_factory=_fallback_planning_note,
                ),
                lambda: _run_understanding_task(
                    state,
                    task_name="material_note",
                    event="planner.material_note.fallback",
                    payload_key="material_note",
                    fallback_detail="资料边界模型响应较慢，已先用已解析资料概况生成兜底边界说明。",
                    factory=lambda: _summarize_materials(state),
                    fallback_factory=_fallback_material_note,
                ),
            ],
            lambda task: task(),
        )
        await emit_planner_event(
            state,
            event="planner.analysis.ready",
            detail="规划判断和资料边界已完成，开始并行生成课程身份和正式方案。",
            payload={"planning_note": compose_planning_note(planning_note, material_note)},
        )
        return {"planning_note": planning_note, "material_note": material_note}

    return understand_goal_and_materials_node


__all__ = ["build_understand_goal_and_materials_node"]
