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
from app.workflows.digest.planner.lib.models import PlannerMaterialSummary
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_course_name
from app.workflows.digest.planner.prompts.intent_summary import (
    build_material_summary_messages,
    build_stream_intent_prompt,
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


async def _stream_intent(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    prompt = build_stream_intent_prompt(
        course_name=_course_for_prompt(state),
        user_prompt=state.get("user_prompt") or "",
        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
        material_context=material_context,
        message_history=list(state.get("message_history", [])),
    )
    tokens: list[str] = []
    started_at = time.monotonic()
    first_token_ms: int | None = None
    await emit_planner_event(state, event="planner.intent.started", detail="正在识别学习意图和规划边界。")
    stream = acompletion_stream(
        [{"role": "user", "content": prompt}],
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.STREAM_INTENT,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="流式生成 intent",
        ),
    )
    async for token in stream:
        if first_token_ms is None:
            first_token_ms = int((time.monotonic() - started_at) * 1000)
        tokens.append(token)
        await emit_planner_token(state, token)
    text = "".join(tokens).strip()
    logger.info(
        "planner_intent_stream_completed",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id") or "",
        first_token_ms=first_token_ms,
        intent_chars=len(text),
    )
    if not text:
        raise ValueError("planner intent stream returned empty text")
    await emit_planner_event(
        state,
        event="planner.intent.ready",
        detail="学习意图已识别，准备结合资料摘要生成方案。",
        payload={"intent": text},
    )
    return text


async def _summarize_materials(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    await emit_planner_event(state, event="planner.summary.started", detail="正在摘要资料和学科情况。")
    result = await acompletion_with_fallback(
        build_material_summary_messages(
            course_name=_course_for_prompt(state),
            user_prompt=state.get("user_prompt") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            material_context=material_context,
        ),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.SUMMARIZE_MATERIALS,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="生成 summary",
        ),
        response_model=PlannerMaterialSummary,
    )
    summary = result.summary.strip() if isinstance(result, PlannerMaterialSummary) else PlannerMaterialSummary.model_validate(result).summary.strip()
    if not summary:
        raise ValueError("planner material summary returned empty text")
    await emit_planner_event(
        state,
        event="planner.summary.ready",
        detail="资料摘要已生成。",
        payload={"summary": summary},
    )
    return summary


def build_understand_goal_and_materials_node(*, context: WorkflowContext):
    """Build the intent + summary fan-out node."""

    del context

    async def understand_goal_and_materials_node(state: BuildPlannerState) -> dict:
        if state.get("error"):
            return {}
        if str(state.get("planner_operation") or "") != "create":
            latest_plan = dict(state.get("latest_plan") or {})
            return {
                "intent": str(latest_plan.get("intent") or ""),
                "summary": str(latest_plan.get("summary") or ""),
            }

        logger.info(
            "planner_intent_summary_node_started",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
        )
        intent, summary = await run_llm_tasks(
            [
                lambda: _stream_intent(state),
                lambda: _summarize_materials(state),
            ],
            lambda task: task(),
        )
        await emit_planner_event(
            state,
            event="planner.analysis.ready",
            detail="intent 与 summary 已完成，开始并行生成课程身份和正式方案。",
            payload={"intent": intent, "summary": summary},
        )
        return {"intent": intent, "summary": summary}

    return understand_goal_and_materials_node


__all__ = ["build_understand_goal_and_materials_node"]
