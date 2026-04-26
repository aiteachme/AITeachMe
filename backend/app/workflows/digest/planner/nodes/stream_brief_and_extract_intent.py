"""Stream visible thinking while generating internal plan intent."""

from __future__ import annotations

import asyncio
import time

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.plan_sketch import parse_planner_brief_text
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_subject_display_name
from app.workflows.digest.planner.lib.models import (
    PlanIntent,
    PlannerBrief,
    build_empty_planner_brief,
)
from app.workflows.digest.planner.prompts import build_plan_intent_messages, build_plan_sketch_prompt
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _subject_for_prompt(state: BuildPlannerState) -> str:
    """Return a human-readable subject; never leak subj_* ids into prompts."""

    material_context = state["material_context"]
    return _resolve_subject_display_name(
        state["subject"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


async def _stream_planner_brief(state: BuildPlannerState, fallback: PlannerBrief) -> PlannerBrief:
    material_context = state["material_context"]
    subject_name = _subject_for_prompt(state)
    prompt = build_plan_sketch_prompt(
        subject=subject_name,
        user_prompt=state.get("user_prompt") or "",
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
            **planner_completion_kwargs_with_metadata(
                PlannerModelStep.STREAM_BRIEF,
                planner_session_id=state.get("planner_session_id") or "",
                substep="生成可见判断",
            ),
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


async def _extract_plan_intent(state: BuildPlannerState) -> PlanIntent:
    material_context = state["material_context"]
    try:
        logger.info(
            "planner_plan_intent_llm_starting",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject", ""),
            material_digest_chars=len(material_context.material_digest or ""),
        )
        plan_intent = await acompletion_with_fallback(
            build_plan_intent_messages(
                subject=_subject_for_prompt(state),
                user_prompt=state.get("user_prompt") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                material_context=material_context,
                message_history=list(state.get("message_history", [])),
            ),
            **planner_completion_kwargs_with_metadata(
                PlannerModelStep.EXTRACT_INTENT,
                planner_session_id=state.get("planner_session_id") or "",
                substep="生成规划抓手",
            ),
            response_model=PlanIntent,
        )
        plan_intent.plan_queries = _normalize_plan_queries(
            [*plan_intent.plan_queries, *_fallback_plan_queries(state)]
        )
        if not plan_intent.plan_intent.strip():
            plan_intent.plan_intent = _fallback_plan_intent(state)
        logger.info(
            "planner_plan_intent_llm_completed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject", ""),
            plan_intent_chars=len(plan_intent.plan_intent or ""),
            query_count=len(plan_intent.plan_queries),
        )
        return plan_intent
    except Exception:
        logger.exception(
            "planner_plan_intent_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
        )
        await emit_planner_event(
            state,
            event="planner.intent.failed",
            detail="规划抓手生成失败，请调整目标后重试。",
        )
        raise


def _normalize_plan_queries(queries: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in queries:
        text = " ".join(str(raw or "").split()).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned[:8]


def _fallback_plan_queries(state: BuildPlannerState) -> list[str]:
    material_context = state["material_context"]
    goal = str(state.get("user_prompt") or "").strip()
    subject = _subject_for_prompt(state)
    mode = str(state.get("digest_mode") or material_context.course_mode_decision.mode.value)
    candidates = [
        f"{goal or '当前主题'} 核心知识簇",
        f"{goal or '当前主题'} 题型与易错点",
        f"{goal or '当前主题'} 初步大纲拆分",
        f"{subject} {mode} 学习计划",
    ]
    return [item for item in candidates if item.strip()]


def _fallback_plan_intent(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    goal = str(state.get("user_prompt") or "").strip()
    mode = str(state.get("digest_mode") or material_context.course_mode_decision.mode.value)
    return f"用户意图暂按 {mode} 学习处理；围绕{goal or '当前学习目标'}和已上传资料，先识别资料主线，再生成可调整的初步大纲。"


def build_stream_brief_and_extract_intent_node(*, context: WorkflowContext):
    async def stream_brief_and_extract_intent_node(state: BuildPlannerState) -> dict:
        logger.info(
            "planner_brief_intent_node_started",
            planner_session_id=state.get("planner_session_id", ""),
            subject=state.get("subject", ""),
        )
        fallback_brief = build_empty_planner_brief()
        brief, plan_intent = await asyncio.gather(
            _stream_planner_brief(state, fallback_brief),
            _extract_plan_intent(state),
        )
        await emit_planner_event(
            state,
            event="planner.intent.ready",
            detail=f"已整理出 {len(plan_intent.plan_queries)} 个规划抓手，准备生成计划和初步大纲。",
            payload={
                "query_count": len(plan_intent.plan_queries),
            },
        )
        result = {
            "planner_brief": brief.model_dump(mode="json"),
            "plan_intent": plan_intent.model_dump(mode="json"),
        }
        logger.info(
            "planner_brief_intent_node_completed",
            planner_session_id=state.get("planner_session_id", ""),
            brief_chars=len(brief.markdown or ""),
            query_count=len(plan_intent.plan_queries),
        )
        return result

    return stream_brief_and_extract_intent_node


__all__ = ["build_stream_brief_and_extract_intent_node"]
