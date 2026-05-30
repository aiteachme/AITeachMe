"""Stream visible thinking while generating internal plan intent."""

from __future__ import annotations

import json
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
        messages = build_plan_intent_messages(
            course_name=_course_for_prompt(state),
            user_prompt=state.get("user_prompt") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            material_context=material_context,
            message_history=list(state.get("message_history", [])),
            latest_feedback=state.get("feedback_message") or "",
            latest_plan=state.get("latest_plan"),
            existing_doc_context=state.get("existing_doc_context"),
            planner_context_mode=state.get("planner_context_mode") or "fresh_build",
        )
        plan_intent = await acompletion_with_fallback(
            messages,
            **planner_completion_kwargs_with_metadata(
                PlannerModelStep.EXTRACT_INTENT,
                model_override=state.get("model_override"),
                planner_session_id=state.get("planner_session_id") or "",
                substep="生成规划抓手",
            ),
            response_model=PlanIntent,
        )
        plan_intent = _normalize_plan_intent(plan_intent)
        validation_errors = _plan_intent_validation_errors(plan_intent)
        if validation_errors:
            logger.warning(
                "planner_plan_intent_invalid_repairing_with_llm",
                planner_session_id=state.get("planner_session_id") or "",
                course_id=state.get("course_id", ""),
                validation_errors=validation_errors,
            )
            await emit_planner_event(
                state,
                event="planner.intent.repairing",
                detail="规划抓手结构不完整，正在让模型重新生成内部规划意图...",
                payload={"validation_errors": validation_errors},
            )
            plan_intent = await acompletion_with_fallback(
                _build_plan_intent_repair_messages(
                    messages,
                    invalid_intent=plan_intent,
                    validation_errors=validation_errors,
                ),
                **planner_completion_kwargs_with_metadata(
                    PlannerModelStep.EXTRACT_INTENT,
                    model_override=state.get("model_override"),
                    planner_session_id=state.get("planner_session_id") or "",
                    substep="修复规划抓手",
                    repair_reason="invalid_plan_intent_contract",
                ),
                response_model=PlanIntent,
            )
            plan_intent = _normalize_plan_intent(plan_intent)
            validation_errors = _plan_intent_validation_errors(plan_intent)
            if validation_errors:
                raise ValueError(
                    "planner PlanIntent invalid after LLM repair: "
                    + ", ".join(validation_errors)
                )
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


def _normalize_plan_intent(plan_intent: PlanIntent) -> PlanIntent:
    """Normalize transport noise only; semantic repair must stay in the LLM."""

    return plan_intent.model_copy(update={"plan_queries": _normalize_plan_queries(plan_intent.plan_queries)})


def _plan_intent_validation_errors(plan_intent: PlanIntent) -> list[str]:
    errors: list[str] = []
    if not plan_intent.plan_intent.strip():
        errors.append("empty_plan_intent")
    if not plan_intent.plan_queries:
        errors.append("empty_plan_queries")
    return errors


def _build_plan_intent_repair_messages(
    messages: list[dict[str, str]],
    *,
    invalid_intent: PlanIntent,
    validation_errors: list[str],
) -> list[dict[str, str]]:
    invalid_json = json.dumps(
        invalid_intent.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    repair_prompt = f"""
上一次结构化 PlanIntent 不完整，不能继续使用。
校验错误：{", ".join(validation_errors)}
上一次 JSON：{invalid_json}

请重新阅读上面的用户提示、资料画像、资料上下文、本轮最新输入、上一版方案和最近对话，由模型重新判断并输出完整 PlanIntent。
不要返回补丁，不要解释，不要复述错误原因，只输出完整合法 JSON。

硬性要求：
1. plan_intent 必须是非空中文短句，说明本轮学习规划或方案修订意图。
2. plan_queries 必须至少 3 条，必须服务本轮意图识别和后续大纲合成。
3. 如果用户给出章数、范围、专题或编辑模式，必须由你基于完整上下文判断对应字段，不要省略 target_scope、scope_decision、chapter_count_guidance、requested_chapter_count 或 plan_change_mode。
4. adjustment_options 必须给出后续可继续调整的方向。
""".strip()
    return [*messages, {"role": "user", "content": repair_prompt}]


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
