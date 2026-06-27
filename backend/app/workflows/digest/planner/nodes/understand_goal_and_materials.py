"""Understand the learning goal and material scope before composing a plan."""

from __future__ import annotations

import time

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback, run_llm_tasks
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.models import PlannerMaterialNote
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_course_name, compose_planning_note
from app.workflows.digest.planner.prompts.goal_materials import (
    build_material_note_messages,
    build_stream_planning_note_prompt,
)
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _course_for_prompt(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    return _resolve_course_name(
        state["course_id"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


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
        try:
            planning_note, material_note = await run_llm_tasks(
                [
                    lambda: _stream_planning_note(state),
                    lambda: _summarize_materials(state),
                ],
                lambda task: task(),
            )
        except Exception as exc:
            logger.exception(
                "planner_analysis_generation_failed",
                planner_session_id=state.get("planner_session_id") or "",
                course_id=state.get("course_id") or "",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await emit_planner_event(
                state,
                event="planner.analysis.failed",
                detail="规划判断或资料边界生成失败，请重试。",
                payload={"error_type": type(exc).__name__},
            )
            raise
        await emit_planner_event(
            state,
            event="planner.analysis.ready",
            detail="规划判断和资料边界已完成，开始并行生成课程身份和正式方案。",
            payload={"planning_note": compose_planning_note(planning_note, material_note)},
        )
        return {"planning_note": planning_note, "material_note": material_note}

    return understand_goal_and_materials_node


__all__ = ["build_understand_goal_and_materials_node"]
