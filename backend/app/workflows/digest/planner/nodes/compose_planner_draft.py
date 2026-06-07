"""Compose a planner draft and stream the user-visible plan text."""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import _resolve_course_name
from app.workflows.digest.planner.prompts.build_plan_composer import (
    CHAPTERS_END,
    CHAPTERS_START,
    PLAN_END,
    PLAN_START,
    SUGGESTION_END,
    SUGGESTION_START,
    build_planner_stream_messages,
)
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _course_for_prompt(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    latest_plan = dict(state.get("latest_plan") or {})
    return str(latest_plan.get("course_name") or "").strip() or _resolve_course_name(
        state["course_id"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _extract_between(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise ValueError(f"missing {start}")
    content_start = start_index + len(start)
    end_index = text.find(end, content_start)
    if end_index < 0:
        raise ValueError(f"missing {end}")
    return text[content_start:end_index].strip()


def _partial_plan_content(text: str) -> str:
    start_index = text.find(PLAN_START)
    if start_index < 0:
        return ""
    content_start = start_index + len(PLAN_START)
    end_index = text.find(PLAN_END, content_start)
    content = text[content_start:] if end_index < 0 else text[content_start:end_index]
    for prefix_len in range(len(PLAN_END) - 1, 0, -1):
        if content.endswith(PLAN_END[:prefix_len]):
            content = content[:-prefix_len]
            break
    return content


def _string_list(value: Any) -> list[str]:
    items = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _parse_chapters(value: str) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"chapters json invalid: {exc}") from exc
    if not isinstance(decoded, list):
        raise ValueError("chapters must be a JSON array")
    chapters: list[dict[str, Any]] = []
    for index, raw in enumerate(decoded, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"chapter #{index} must be an object")
        title = _clean_text(raw.get("title"))
        key_points = _string_list(raw.get("key_points"))
        if not title:
            raise ValueError(f"chapter #{index} is missing title")
        if not key_points:
            raise ValueError(f"chapter `{title}` is missing key_points")
        chapters.append(
            {
                "chapter_index": index,
                "title": title,
                "objective": "；".join(key_points),
                "required_elements": key_points,
                "writing_instructions": "围绕本章知识点生成清晰讲解。",
            }
        )
    return chapters


def _parse_planner_response(text: str) -> dict[str, Any]:
    plan = _clean_text(_extract_between(text, PLAN_START, PLAN_END))
    suggestion = _clean_text(_extract_between(text, SUGGESTION_START, SUGGESTION_END))
    chapters = _parse_chapters(_extract_between(text, CHAPTERS_START, CHAPTERS_END))
    if not plan:
        raise ValueError("planner response is missing plan")
    if not suggestion:
        raise ValueError("planner response is missing suggestion")
    return {"suggestion": suggestion, "plan": plan, "chapters": chapters}


def _plan_preview_payload(state: BuildPlannerState, payload: dict[str, Any]) -> dict[str, Any]:
    latest_plan = dict(state.get("latest_plan") or {})
    return {
        "course_id": state.get("course_id", ""),
        "selected_file_ids": list(state.get("selected_file_ids") or state.get("requested_file_ids") or []),
        "user_prompt": state.get("user_prompt") or latest_plan.get("user_prompt") or "",
        "digest_mode": state.get("digest_mode") or latest_plan.get("digest_mode") or "systematic",
        "intent": str(state.get("intent") or latest_plan.get("intent") or ""),
        "summary": str(state.get("summary") or latest_plan.get("summary") or ""),
        "course_name": str(latest_plan.get("course_name") or ""),
        "course_icon": str(latest_plan.get("course_icon") or ""),
        "suggestion": str(payload.get("suggestion") or ""),
        "plan": str(payload.get("plan") or ""),
        "chapters": list(payload.get("chapters") or []),
        "build_constraints": dict(payload.get("build_constraints") or {}),
        "status": "planning",
        "planner_session_id": state.get("planner_session_id") or None,
        "confirmed_plan_id": None,
        "model_override": state.get("model_override"),
    }


async def _stream_planner_response(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    latest_plan = dict(state.get("latest_plan") or {})
    intent = str(state.get("intent") or latest_plan.get("intent") or "").strip()
    summary = str(state.get("summary") or latest_plan.get("summary") or "").strip()
    messages = build_planner_stream_messages(
        course_name=_course_for_prompt(state),
        user_prompt=state.get("user_prompt") or latest_plan.get("user_prompt") or "",
        digest_mode=state.get("digest_mode") or latest_plan.get("digest_mode") or material_context.course_mode_decision.mode.value,
        material_context=material_context,
        intent=intent,
        summary=summary,
        message_history=list(state.get("message_history", [])),
        latest_feedback=state.get("feedback_message") or "",
        latest_plan=latest_plan or None,
    )
    await emit_planner_event(
        state,
        event="planner.plan.started",
        detail="正在生成 plan、suggestion 和 chapters。",
    )
    raw_tokens: list[str] = []
    emitted_plan_chars = 0
    emitted_separator = False
    stream = acompletion_stream(
        messages,
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.DRAFT_PLAN,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="流式生成 planner",
        ),
    )
    async for token in stream:
        raw_tokens.append(token)
        raw_text = "".join(raw_tokens)
        visible_plan = _partial_plan_content(raw_text)
        if len(visible_plan) > emitted_plan_chars:
            delta = visible_plan[emitted_plan_chars:]
            emitted_plan_chars = len(visible_plan)
            if not emitted_separator:
                await emit_planner_token(state, "\n\n")
                emitted_separator = True
            await emit_planner_token(state, delta)
    return "".join(raw_tokens).strip()


def build_compose_planner_draft_node(*, context: WorkflowContext):
    """Build the planner draft composer node."""

    del context

    async def compose_planner_draft_node(state: BuildPlannerState) -> dict:
        if state.get("error"):
            return {}

        logger.info(
            "planner_draft_node_started",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
            planner_operation=state.get("planner_operation", ""),
        )
        try:
            raw_output = await _stream_planner_response(state)
            parsed = _parse_planner_response(raw_output)
        except Exception as exc:
            logger.exception(
                "planner_draft_parse_failed",
                planner_session_id=state.get("planner_session_id") or "",
                course_id=state.get("course_id") or "",
                error=str(exc),
            )
            await emit_planner_event(
                state,
                event="planner.plan.failed",
                detail="模型没有按 planner 协议返回 suggestion、plan 和 chapters，请重试。",
            )
            raise

        latest_plan = dict(state.get("latest_plan") or {})
        draft_payload = {
            "intent": str(state.get("intent") or latest_plan.get("intent") or ""),
            "summary": str(state.get("summary") or latest_plan.get("summary") or ""),
            "course_name": str(latest_plan.get("course_name") or ""),
            "course_icon": str(latest_plan.get("course_icon") or ""),
            **parsed,
            "build_constraints": {},
        }
        await emit_planner_event(
            state,
            event="planner.plan.ready",
            detail=f"planner 已生成：{len(parsed.get('chapters') or [])} 个章节。",
            payload={
                "chapter_count": len(parsed.get("chapters") or []),
                "plan_preview": _plan_preview_payload(state, draft_payload),
            },
        )
        logger.info(
            "planner_draft_node_completed",
            planner_session_id=state.get("planner_session_id", ""),
            plan_chars=len(str(parsed.get("plan") or "")),
            suggestion_chars=len(str(parsed.get("suggestion") or "")),
            chapter_count=len(parsed.get("chapters") or []),
        )
        return {
            "build_plan_draft": draft_payload,
            "plan_outline_markdown": str(parsed.get("plan") or ""),
        }

    return compose_planner_draft_node


__all__ = [
    "_parse_planner_response",
    "build_compose_planner_draft_node",
]
