"""Bootstrap a visible plan sketch and structured learning intent in parallel."""

from __future__ import annotations

import asyncio
import time

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.plan_sketch import parse_plan_sketch_text
from app.workflows.digest.planner.lib.evidence_probe import fallback_probe_queries
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_subject_display_name, build_fallback_plan
from app.workflows.digest.planner.lib.models import (
    LearningIntentProfile,
    PlanSketch,
    build_default_intent_profile,
    build_fallback_plan_sketch,
)
from app.workflows.digest.planner.prompts import build_learning_intent_messages, build_plan_sketch_prompt
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


async def _stream_plan_sketch(state: BuildPlannerState, fallback: PlanSketch) -> PlanSketch:
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
        tone=state.get("tone") or "encouraging",
        material_context=material_context,
        message_history=list(state.get("message_history", [])),
    )
    tokens: list[str] = []
    started_at = time.monotonic()
    first_token_ms: int | None = None
    await emit_planner_event(state, event="planner.thinking.started", detail="正在理解资料边界和学习目标...")
    try:
        stream = acompletion_stream(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.REASONING,
            model="reason",
            temperature=0.2,
            max_tokens=780,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "stream_visible_thinking",
            },
        )
        async for token in stream:
            if first_token_ms is None:
                first_token_ms = int((time.monotonic() - started_at) * 1000)
                logger.info(
                    "planner_sketch_first_token_received",
                    planner_session_id=state.get("planner_session_id") or "",
                    subject=state["subject"],
                    first_token_ms=first_token_ms,
                )
            tokens.append(token)
            await emit_planner_token(state, token)
            await emit_planner_event(
                state,
                event="planner.thinking.delta",
                detail="思考过程生成中...",
                payload={"token": token},
            )
    except Exception:
        logger.exception(
            "planner_sketch_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
            token_count=len(tokens),
            first_token_ms=first_token_ms,
        )
        await emit_planner_event(
            state,
            event="planner.fallback.used",
            detail="思考过程生成失败，已使用规则摘要继续。",
        )
        if not tokens:
            for line in fallback.raw_text.splitlines(keepends=True):
                await emit_planner_token(state, line)
        return fallback
    if not tokens:
        await emit_planner_event(
            state,
            event="planner.fallback.used",
            detail="思考过程未返回任何增量内容，已使用规则摘要继续。",
        )
        for line in fallback.raw_text.splitlines(keepends=True):
            await emit_planner_token(state, line)
        return fallback
    return parse_plan_sketch_text("".join(tokens).strip(), fallback=fallback)


async def _extract_learning_intent(state: BuildPlannerState) -> LearningIntentProfile:
    material_context = state["material_context"]
    fallback = build_default_intent_profile(
        material_context=material_context,
        user_goal=state.get("user_goal") or "",
        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
    )
    try:
        intent = await acompletion_with_fallback(
            build_learning_intent_messages(
                subject=state["subject"],
                user_goal=state.get("user_goal") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                material_context=material_context,
                message_history=list(state.get("message_history", [])),
            ),
            task_type=TaskType.CLASSIFY,
            model="light",
            response_model=LearningIntentProfile,
            temperature=0.1,
            max_tokens=420,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "extract_learning_intent",
            },
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
            event="planner.fallback.used",
            detail="意图识别失败，已使用规则意图继续。",
        )
        return fallback


def build_bootstrap_plan_brief_node(*, context: WorkflowContext):
    async def bootstrap_plan_brief_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        fallback_plan = build_fallback_plan(
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            tone=state.get("tone") or "encouraging",
            shared_inputs=material_context,
        )
        fallback_sketch = build_fallback_plan_sketch(fallback_plan)
        sketch, intent = await asyncio.gather(
            _stream_plan_sketch(state, fallback_sketch),
            _extract_learning_intent(state),
        )
        await emit_planner_event(
            state,
            event="planner.intent.ready",
            detail=f"已识别学习目标：{intent.goal_type}，准备调用全部可用检索器校准大纲。",
            payload={
                "goal_type": intent.goal_type,
                "source_policy": "all_available",
                "success_criteria": list(intent.success_criteria[:3]),
            },
        )
        concept_queries = fallback_probe_queries(material_context, plan_sketch=sketch)
        return {
            "plan_sketch_markdown": sketch.raw_text,
            "plan_sketch_text": sketch.raw_text,
            "plan_sketch": sketch.model_dump(mode="json"),
            "learning_intent_profile": intent.model_dump(mode="json"),
            "research_probe_plan": intent.research_probe_plan.model_dump(mode="json"),
            "concept_queries": concept_queries,
        }

    return bootstrap_plan_brief_node


__all__ = ["build_bootstrap_plan_brief_node"]
