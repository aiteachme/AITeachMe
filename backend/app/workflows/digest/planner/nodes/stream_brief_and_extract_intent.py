"""Stream the visible brief while extracting structured learning intent."""

from __future__ import annotations

import asyncio
import time

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.plan_sketch import parse_planner_brief_text
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_subject_display_name
from app.workflows.digest.planner.lib.models import (
    LearningIntent,
    PlannerBrief,
    build_empty_planner_brief,
)
from app.workflows.digest.planner.prompts import build_learning_intent_messages, build_plan_sketch_prompt
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


async def _stream_planner_brief(state: BuildPlannerState, fallback: PlannerBrief) -> PlannerBrief:
    material_context = state["material_context"]
    subject_name = _resolve_subject_display_name(
        state["subject"],
        shared_inputs=material_context,
        user_goal=state.get("user_goal") or "",
    )
    prompt = build_plan_sketch_prompt(
        subject=subject_name,
        user_goal=state.get("user_goal") or "",
        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
        material_context=material_context,
        message_history=list(state.get("message_history", [])),
    )
    logger.info(
        "planner_brief_llm_starting",
        planner_session_id=state.get("planner_session_id") or "",
        subject=state.get("subject", ""),
        prompt_chars=len(prompt),
        material_digest_chars=len(material_context.material_digest or ""),
    )
    tokens: list[str] = []
    started_at = time.monotonic()
    first_token_ms: int | None = None
    await emit_planner_event(state, event="planner.thinking.started", detail="正在理解资料边界和学习目标...")
    try:
        stream = acompletion_stream(
            [{"role": "user", "content": prompt}],
            call_purpose=LLMCallPurpose.GENERATE,
            model="reason",
            max_tokens=780,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "生成可见判断",
            },
        )
        async for token in stream:
            if first_token_ms is None:
                first_token_ms = int((time.monotonic() - started_at) * 1000)
                logger.info(
                    "planner_brief_first_token_received",
                    planner_session_id=state.get("planner_session_id") or "",
                    subject=state["subject"],
                    first_token_ms=first_token_ms,
                )
            tokens.append(token)
            await emit_planner_token(state, token)
    except Exception:
        logger.exception(
            "planner_brief_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
            token_count=len(tokens),
            first_token_ms=first_token_ms,
        )
        await emit_planner_event(
            state,
            event="planner.thinking.failed",
            detail="思考过程生成失败，未得到可展示的规划判断。",
        )
        return fallback
    if not tokens:
        await emit_planner_event(
            state,
            event="planner.thinking.empty",
            detail="思考过程未返回任何增量内容。",
        )
        return fallback
    text = "".join(tokens).strip()
    logger.info(
        "planner_brief_llm_completed",
        planner_session_id=state.get("planner_session_id") or "",
        subject=state.get("subject", ""),
        token_count=len(tokens),
        text_chars=len(text),
    )
    return parse_planner_brief_text(text, fallback=fallback)


async def _extract_learning_intent(state: BuildPlannerState) -> LearningIntent:
    material_context = state["material_context"]
    try:
        logger.info(
            "planner_intent_llm_starting",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject", ""),
            material_digest_chars=len(material_context.material_digest or ""),
        )
        intent = await acompletion_with_fallback(
            build_learning_intent_messages(
                subject=state["subject"],
                user_goal=state.get("user_goal") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                material_context=material_context,
                message_history=list(state.get("message_history", [])),
            ),
            call_purpose=LLMCallPurpose.CLASSIFY,
            model="primary",
            response_model=LearningIntent,
            max_tokens=900,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "识别学习意图",
            },
        )
        logger.info(
            "planner_intent_llm_completed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject", ""),
            goal_type=intent.goal_type,
            focus_concept_count=len(intent.focus_concepts),
            success_criteria_count=len(intent.success_criteria),
        )
        return intent
    except Exception:
        logger.exception(
            "planner_intent_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
        )
        await emit_planner_event(
            state,
            event="planner.intent.failed",
            detail="意图识别失败，请调整目标后重试。",
        )
        raise


def build_stream_brief_and_extract_intent_node(*, context: WorkflowContext):
    async def stream_brief_and_extract_intent_node(state: BuildPlannerState) -> dict:
        logger.info(
            "planner_brief_intent_node_started",
            planner_session_id=state.get("planner_session_id", ""),
            subject=state.get("subject", ""),
        )
        fallback_brief = build_empty_planner_brief()
        brief, intent = await asyncio.gather(
            _stream_planner_brief(state, fallback_brief),
            _extract_learning_intent(state),
        )
        await emit_planner_event(
            state,
            event="planner.intent.ready",
            detail=f"已识别学习目标：{intent.goal_type}，准备直接合成计划大纲。",
            payload={
                "goal_type": intent.goal_type,
                "success_criteria": list(intent.success_criteria),
                "constraints": list(intent.constraints),
                "focus_concepts": list(intent.focus_concepts),
            },
        )
        result = {
            "planner_brief": brief.model_dump(mode="json"),
            "learning_intent": intent.model_dump(mode="json"),
        }
        logger.info(
            "planner_brief_intent_node_completed",
            planner_session_id=state.get("planner_session_id", ""),
            brief_chars=len(brief.markdown or ""),
            goal_type=intent.goal_type,
        )
        return result

    return stream_brief_and_extract_intent_node


__all__ = ["build_stream_brief_and_extract_intent_node"]
