"""Stream visible thinking while generating internal plan intent."""

from __future__ import annotations

import time

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback, run_llm_tasks
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.plan_sketch import parse_planner_brief_text
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_course_name
from app.workflows.digest.planner.lib.models import (
    PlanIntent,
    PlannerBrief,
    build_empty_planner_brief,
)
from app.workflows.digest.planner.prompts.plan_intent import build_plan_intent_messages
from app.workflows.digest.planner.prompts.plan_sketch import build_plan_sketch_prompt
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _course_for_prompt(state: BuildPlannerState) -> str:
    """Return a human-readable course; never leak generated ids into prompts."""

    material_context = state["material_context"]
    return _resolve_course_name(
        state["course_id"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


async def _stream_planner_brief(state: BuildPlannerState, empty_brief: PlannerBrief) -> PlannerBrief:
    material_context = state["material_context"]
    course_name = _course_for_prompt(state)
    prompt = build_plan_sketch_prompt(
        course_name=course_name,
        user_prompt=state.get("user_prompt") or "",
        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
        material_context=material_context,
        message_history=list(state.get("message_history", [])),
        latest_feedback=state.get("feedback_message") or "",
        latest_plan=state.get("latest_plan"),
        existing_doc_context=state.get("existing_doc_context"),
        planner_context_mode=state.get("planner_context_mode") or "fresh_build",
    )
    logger.info(
        "planner_brief_llm_starting",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id", ""),
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
                model_override=state.get("model_override"),
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
                    course_id=state["course_id"],
                    first_token_ms=first_token_ms,
                )
            tokens.append(token)
            await emit_planner_token(state, token)
    except Exception:
        logger.exception(
            "planner_brief_failed",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state["course_id"],
            token_count=len(tokens),
            first_token_ms=first_token_ms,
        )
        await emit_planner_event(
            state,
            event="planner.thinking.failed",
            detail="思考过程生成失败，未得到可展示的规划判断。",
        )
        return empty_brief
    if not tokens:
        await emit_planner_event(
            state,
            event="planner.thinking.empty",
            detail="思考过程未返回任何增量内容。",
        )
        return empty_brief
    text = "".join(tokens).strip()
    logger.info(
        "planner_brief_llm_completed",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id", ""),
        token_count=len(tokens),
        text_chars=len(text),
    )
    return parse_planner_brief_text(text, base_brief=empty_brief)


async def _extract_plan_intent(state: BuildPlannerState) -> PlanIntent:
    material_context = state["material_context"]
    try:
        logger.info(
            "planner_plan_intent_llm_starting",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id", ""),
            material_digest_chars=len(material_context.material_digest or ""),
        )
        plan_intent = await acompletion_with_fallback(
            build_plan_intent_messages(
                course_name=_course_for_prompt(state),
                user_prompt=state.get("user_prompt") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                material_context=material_context,
                message_history=list(state.get("message_history", [])),
                latest_feedback=state.get("feedback_message") or "",
                latest_plan=state.get("latest_plan"),
                existing_doc_context=state.get("existing_doc_context"),
                planner_context_mode=state.get("planner_context_mode") or "fresh_build",
            ),
            **planner_completion_kwargs_with_metadata(
                PlannerModelStep.EXTRACT_INTENT,
                model_override=state.get("model_override"),
                planner_session_id=state.get("planner_session_id") or "",
                substep="生成规划抓手",
            ),
            response_model=PlanIntent,
        )
        plan_intent.plan_queries = _normalize_plan_queries(plan_intent.plan_queries)
        if not plan_intent.plan_intent.strip():
            raise ValueError("planner PlanIntent returned empty plan_intent")
        if not plan_intent.plan_queries:
            raise ValueError("planner PlanIntent returned empty plan_queries")
        await emit_planner_event(
            state,
            event="planner.intent.scope",
            detail=_plan_intent_progress_detail(plan_intent),
            payload={
                "target_scope": plan_intent.target_scope.strip(),
                "scope_decision": plan_intent.scope_decision.strip(),
                "chapter_count_guidance": plan_intent.chapter_count_guidance.strip(),
                "plan_change_mode": plan_intent.plan_change_mode.strip(),
                "requested_chapter_count": plan_intent.requested_chapter_count,
                "query_count": len(plan_intent.plan_queries),
            },
        )
        logger.info(
            "planner_plan_intent_llm_completed",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id", ""),
            plan_intent_chars=len(plan_intent.plan_intent or ""),
            query_count=len(plan_intent.plan_queries),
        )
        return plan_intent
    except Exception:
        logger.exception(
            "planner_plan_intent_failed",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state["course_id"],
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


def _plan_intent_progress_detail(plan_intent: PlanIntent) -> str:
    change_mode = plan_intent.plan_change_mode.strip()
    target_scope = plan_intent.target_scope.strip()
    scope_decision = plan_intent.scope_decision.strip()
    chapter_count_guidance = plan_intent.chapter_count_guidance.strip()
    requested_count = plan_intent.requested_chapter_count
    count_suffix = f"，按用户指定生成 {requested_count} 章" if requested_count else ""
    if change_mode == "replace_existing_outline" and target_scope:
        return f"已判断本轮要把方案重定向到“{target_scope}”{count_suffix}：{scope_decision or '旧方案只作为上下文，不保留无关章节。'}"
    if target_scope and scope_decision:
        return f"已判断本轮重点是“{target_scope}”{count_suffix}：{scope_decision}"
    if target_scope:
        return f"已判断本轮重点是“{target_scope}”{count_suffix}，后续大纲会围绕这个范围拆分。"
    if chapter_count_guidance:
        return f"已确定章节拆分颗粒度：{chapter_count_guidance}"
    return f"已整理出 {len(plan_intent.plan_queries)} 个规划抓手，准备生成计划和初步大纲。"


def build_stream_brief_and_extract_intent_node(*, context: WorkflowContext):
    async def stream_brief_and_extract_intent_node(state: BuildPlannerState) -> dict:
        logger.info(
            "planner_brief_intent_node_started",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
        )
        empty_brief = build_empty_planner_brief()
        brief, plan_intent = await run_llm_tasks(
            [
                lambda: _stream_planner_brief(state, empty_brief),
                lambda: _extract_plan_intent(state),
            ],
            lambda task: task(),
        )
        await emit_planner_event(
            state,
            event="planner.intent.ready",
            detail=f"{_plan_intent_progress_detail(plan_intent)} 准备生成计划和初步大纲。",
            payload={
                "query_count": len(plan_intent.plan_queries),
                "target_scope": plan_intent.target_scope.strip(),
                "scope_decision": plan_intent.scope_decision.strip(),
                "chapter_count_guidance": plan_intent.chapter_count_guidance.strip(),
                "plan_change_mode": plan_intent.plan_change_mode.strip(),
                "requested_chapter_count": plan_intent.requested_chapter_count,
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
