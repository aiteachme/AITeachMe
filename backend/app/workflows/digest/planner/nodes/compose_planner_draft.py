"""Compose a planner draft and stream the user-visible plan text."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.common.pedagogy import clean_generated_chapter_title
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import (
    _resolve_course_name,
    compose_effective_planner_request_text,
    compose_planning_note,
    normalize_planner_diagnosis_draft,
    normalize_planner_draft,
)
from app.workflows.digest.planner.prompts.build_plan_composer import (
    CHAPTERS_END,
    CHAPTERS_START,
    DIAGNOSE_END,
    DIAGNOSE_START,
    PLAN_END,
    PLAN_START,
    SUGGESTION_END,
    SUGGESTION_START,
    build_planner_diagnosis_messages,
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


def _partial_content_between_markers(text: str, start: str, end: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        return ""
    content_start = start_index + len(start)
    end_index = text.find(end, content_start)
    content = text[content_start:] if end_index < 0 else text[content_start:end_index]
    for prefix_len in range(len(end) - 1, 0, -1):
        if content.endswith(end[:prefix_len]):
            content = content[:-prefix_len]
            break
    return content


def _partial_plan_content(text: str) -> str:
    return _partial_content_between_markers(text, PLAN_START, PLAN_END)


def _partial_suggestion_content(text: str) -> str:
    return _partial_content_between_markers(text, SUGGESTION_START, SUGGESTION_END)


def _decode_json_string_fragment(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        decoded = value
    return _clean_text(decoded)


def _partial_chapters(text: str) -> list[dict[str, Any]]:
    start_index = text.find(CHAPTERS_START)
    if start_index < 0:
        return []
    content_start = start_index + len(CHAPTERS_START)
    end_index = text.find(CHAPTERS_END, content_start)
    content = text[content_start:] if end_index < 0 else text[content_start:end_index]
    title_matches = list(re.finditer(r'"title"\s*:\s*"(?P<title>(?:\\.|[^"\\])*)"', content))
    chapters: list[dict[str, Any]] = []
    for index, match in enumerate(title_matches, start=1):
        title = clean_generated_chapter_title(_decode_json_string_fragment(match.group("title")))
        if not title:
            continue
        next_start = title_matches[index].start() if index < len(title_matches) else len(content)
        segment = content[match.end() : next_start]
        points_match = re.search(r'"key_points"\s*:\s*\[(?P<points>.*?)(?:\]|$)', segment, re.S)
        key_points: list[str] = []
        if points_match:
            key_points = _string_list(
                [
                    _decode_json_string_fragment(item.group("value"))
                    for item in re.finditer(r'"(?P<value>(?:\\.|[^"\\])*)"', points_match.group("points"))
                ]
            )
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": title,
                "objective": "；".join(key_points) if key_points else "正在整理本章重点。",
                "required_elements": key_points,
                "writing_instructions": "围绕本章知识点生成清晰讲解。",
            }
        )
    return chapters


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


def _diagnose_answer_map(raw_answers: Any) -> dict[str, str]:
    if not isinstance(raw_answers, list):
        return {}
    answers: dict[str, str] = {}
    for raw in raw_answers:
        if not isinstance(raw, dict):
            continue
        question = _clean_text(raw.get("question"))
        answer = _clean_text(raw.get("answer"))
        if question and answer:
            answers[question.casefold()] = answer
    return answers


def _latest_plan_with_current_diagnosis(state: BuildPlannerState, latest_plan: dict[str, Any]) -> dict[str, Any]:
    answers = _diagnose_answer_map(state.get("diagnose_answers"))
    status = _clean_text(state.get("diagnose_status"))
    note = _clean_text(state.get("diagnose_note"))
    if not answers and not status and not note:
        return latest_plan
    next_plan = dict(latest_plan)
    diagnose: list[dict[str, Any]] = []
    for raw in list(next_plan.get("diagnose") or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        question = _clean_text(item.get("question"))
        answer = answers.get(question.casefold()) if question else ""
        if answer:
            item["answer"] = answer
        diagnose.append(item)
    if diagnose:
        next_plan["diagnose"] = diagnose
    if status in {"answered", "skipped"}:
        next_plan["diagnose_status"] = status
    elif answers:
        next_plan["diagnose_status"] = "answered"
    if note:
        next_plan["diagnose_note"] = note
    return next_plan


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
        title = clean_generated_chapter_title(_clean_text(raw.get("title")))
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


def _parse_diagnose(value: str) -> list[dict[str, Any]]:
    if not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"diagnose json invalid: {exc}") from exc
    if not isinstance(decoded, list):
        raise ValueError("diagnose must be a JSON array")
    diagnose: list[dict[str, Any]] = []
    for raw in decoded[:5]:
        if not isinstance(raw, dict):
            continue
        question = _clean_text(raw.get("question") or raw.get("title") or raw.get("prompt"))
        if not question:
            continue
        options = _string_list(
            raw.get("options")
            or raw.get("choices")
            or raw.get("sample_answers")
            or raw.get("quick_answers")
            or raw.get("example_answers")
            or raw.get("answers")
        )[:4]
        if len(options) < 2:
            continue
        diagnose.append(
            {
                "question": question,
                "purpose": _clean_text(raw.get("purpose") or raw.get("diagnosis_target") or raw.get("target")),
                "options": options,
                "answer": _clean_text(raw.get("answer") or raw.get("user_answer") or raw.get("selected_answer")),
            }
        )
    return diagnose


def _parse_planner_response(text: str) -> dict[str, Any]:
    plan = _clean_text(_extract_between(text, PLAN_START, PLAN_END))
    suggestion = _clean_text(_extract_between(text, SUGGESTION_START, SUGGESTION_END))
    chapters = _parse_chapters(_extract_between(text, CHAPTERS_START, CHAPTERS_END))
    if not plan:
        raise ValueError("planner response is missing plan")
    if not suggestion:
        raise ValueError("planner response is missing suggestion")
    return {"suggestion": suggestion, "plan": plan, "diagnose": [], "chapters": chapters}


def _parse_diagnosis_response(text: str) -> list[dict[str, Any]]:
    diagnose = _parse_diagnose(_extract_between(text, DIAGNOSE_START, DIAGNOSE_END))
    if not diagnose:
        raise ValueError("planner diagnosis response is missing useful choice questions")
    return diagnose


def _plan_preview_payload(state: BuildPlannerState, payload: dict[str, Any]) -> dict[str, Any]:
    latest_plan = dict(state.get("latest_plan") or {})
    planning_note = str(
        payload.get("planning_note")
        or latest_plan.get("planning_note")
        or compose_planning_note(state.get("planning_note"), state.get("material_note"))
        or ""
    )
    return {
        "course_id": state.get("course_id", ""),
        "selected_file_ids": list(state.get("selected_file_ids") or state.get("requested_file_ids") or []),
        "user_prompt": state.get("user_prompt") or latest_plan.get("user_prompt") or "",
        "digest_mode": state.get("digest_mode") or latest_plan.get("digest_mode") or "systematic",
        "planning_note": planning_note,
        "course_name": str(payload.get("course_name") or latest_plan.get("course_name") or ""),
        "course_icon": str(payload.get("course_icon") or latest_plan.get("course_icon") or ""),
        "suggestion": str(payload.get("suggestion") or ""),
        "plan": str(payload.get("plan") or ""),
        "diagnose": list(payload.get("diagnose") or latest_plan.get("diagnose") or []),
        "diagnose_status": str(payload.get("diagnose_status") or latest_plan.get("diagnose_status") or ""),
        "diagnose_note": str(payload.get("diagnose_note") or latest_plan.get("diagnose_note") or ""),
        "chapters": list(payload.get("chapters") or []),
        "status": "planning",
        "planner_session_id": state.get("planner_session_id") or None,
        "confirmed_plan_id": None,
        "model_override": state.get("model_override"),
    }


async def _stream_planner_response(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    latest_plan = _latest_plan_with_current_diagnosis(state, dict(state.get("latest_plan") or {}))
    planning_note = str(state.get("planning_note") or latest_plan.get("planning_note") or "").strip()
    material_note = str(state.get("material_note") or "").strip()
    messages = build_planner_stream_messages(
        course_name=_course_for_prompt(state),
        user_prompt=state.get("user_prompt") or latest_plan.get("user_prompt") or "",
        digest_mode=state.get("digest_mode") or latest_plan.get("digest_mode") or material_context.course_mode_decision.mode.value,
        material_context=material_context,
        planning_note=planning_note,
        material_note=material_note,
        message_history=list(state.get("message_history", [])),
        latest_feedback=state.get("feedback_message") or "",
        latest_plan=latest_plan or None,
    )
    await emit_planner_event(
        state,
        event="planner.plan.started",
        detail="正在生成方案总说明、修改建议和章节大纲。",
    )
    raw_tokens: list[str] = []
    emitted_plan_chars = 0
    emitted_separator = False
    emitted_suggestion_status = False
    emitted_chapters_status = False
    emitted_chapter_count = 0
    stream = acompletion_stream(
        messages,
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.DRAFT_PLAN,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="流式生成方案",
        ),
    )
    async for token in stream:
        raw_tokens.append(token)
        raw_text = "".join(raw_tokens)
        visible_plan = _partial_plan_content(raw_text)
        if not emitted_suggestion_status and PLAN_END in raw_text:
            emitted_suggestion_status = True
            await emit_planner_event(
                state,
                event="planner.suggestion.started",
                detail="正在整理后续调整建议。",
            )
        if not emitted_chapters_status and (SUGGESTION_END in raw_text or CHAPTERS_START in raw_text):
            emitted_chapters_status = True
            await emit_planner_event(
                state,
                event="planner.chapters.started",
                detail="正在生成章节大纲。",
            )
        partial_chapters = _partial_chapters(raw_text)
        chapter_count = len(partial_chapters)
        if chapter_count > emitted_chapter_count:
            emitted_chapter_count = chapter_count
            payload: dict[str, Any] = {"partial_chapter_count": chapter_count}
            if partial_chapters:
                payload["plan_preview"] = _plan_preview_payload(
                    state,
                    {
                        "suggestion": _partial_suggestion_content(raw_text),
                        "plan": visible_plan,
                        "chapters": partial_chapters,
                    },
                )
            await emit_planner_event(
                state,
                event="planner.chapters.progress",
                detail=f"正在生成章节大纲，已整理 {chapter_count} 个章节。",
                payload=payload,
            )
        if len(visible_plan) > emitted_plan_chars:
            delta = visible_plan[emitted_plan_chars:]
            emitted_plan_chars = len(visible_plan)
            if not emitted_separator:
                await emit_planner_token(state, "\n\n")
                emitted_separator = True
            await emit_planner_token(state, delta)
    return "".join(raw_tokens).strip()


def _should_generate_diagnosis_first(state: BuildPlannerState) -> bool:
    if _clean_text(state.get("planner_operation")).casefold() != "create":
        return False
    if _clean_text(state.get("diagnose_status")):
        return False
    latest_plan = state.get("latest_plan")
    return not isinstance(latest_plan, dict) or not latest_plan


async def _stream_diagnosis_response(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    latest_plan = dict(state.get("latest_plan") or {})
    planning_note = str(state.get("planning_note") or latest_plan.get("planning_note") or "").strip()
    material_note = str(state.get("material_note") or "").strip()
    messages = build_planner_diagnosis_messages(
        course_name=_course_for_prompt(state),
        user_prompt=state.get("user_prompt") or latest_plan.get("user_prompt") or "",
        digest_mode=state.get("digest_mode") or latest_plan.get("digest_mode") or material_context.course_mode_decision.mode.value,
        material_context=material_context,
        planning_note=planning_note,
        material_note=material_note,
        message_history=list(state.get("message_history", [])),
    )
    await emit_planner_event(
        state,
        event="planner.diagnose.started",
        detail="正在生成前置诊断选择题。",
    )
    raw_tokens: list[str] = []
    stream = acompletion_stream(
        messages,
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.DIAGNOSE_QUESTIONS,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="生成前置诊断",
        ),
    )
    async for token in stream:
        raw_tokens.append(token)
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
        if _should_generate_diagnosis_first(state):
            try:
                raw_output = await _stream_diagnosis_response(state)
                diagnose_questions = _parse_diagnosis_response(raw_output)
            except Exception as exc:
                logger.exception(
                    "planner_diagnosis_generation_failed",
                    planner_session_id=state.get("planner_session_id") or "",
                    course_id=state.get("course_id") or "",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                await emit_planner_event(
                    state,
                    event="planner.diagnose.failed",
                    detail="前置诊断生成失败，请重试。",
                    payload={"error_type": type(exc).__name__},
                )
                raise
            latest_plan = dict(state.get("latest_plan") or {})
            planning_note = compose_planning_note(
                state.get("planning_note") or latest_plan.get("planning_note"),
                state.get("material_note"),
            )
            diagnosis_payload = {
                "planner_stage": "diagnosis",
                "planning_note": planning_note,
                "course_name": str(latest_plan.get("course_name") or ""),
                "course_icon": str(latest_plan.get("course_icon") or ""),
                "diagnose": diagnose_questions,
                "diagnose_status": "pending",
                "build_constraints": {},
            }
            material_context = state["material_context"]
            digest_mode = (
                state.get("digest_mode")
                or latest_plan.get("digest_mode")
                or material_context.course_mode_decision.mode.value
            )
            draft_payload = normalize_planner_diagnosis_draft(
                diagnosis_payload,
                course_id=state["course_id"],
                user_prompt=state.get("user_prompt") or latest_plan.get("user_prompt") or "",
                requested_digest_mode=digest_mode,
                shared_inputs=material_context,
                latest_plan=latest_plan or None,
            )
            await emit_planner_event(
                state,
                event="planner.diagnose.ready",
                detail=f"前置诊断已生成：{len(draft_payload.get('diagnose') or [])} 道选择题。",
                payload={
                    "diagnose_count": len(draft_payload.get("diagnose") or []),
                    "plan_preview": _plan_preview_payload(state, draft_payload),
                },
            )
            logger.info(
                "planner_diagnosis_node_completed",
                planner_session_id=state.get("planner_session_id", ""),
                diagnose_count=len(draft_payload.get("diagnose") or []),
            )
            return {
                "build_plan_draft": draft_payload,
                "plan_outline_markdown": "",
            }

        try:
            raw_output = await _stream_planner_response(state)
            parsed = _parse_planner_response(raw_output)
        except Exception as exc:
            logger.exception(
                "planner_draft_generation_failed",
                planner_session_id=state.get("planner_session_id") or "",
                course_id=state.get("course_id") or "",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await emit_planner_event(
                state,
                event="planner.plan.failed",
                detail="方案生成失败或模型没有按协议返回方案内容，请重试。",
                payload={"error_type": type(exc).__name__},
            )
            raise

        latest_plan = _latest_plan_with_current_diagnosis(state, dict(state.get("latest_plan") or {}))
        planning_note = compose_planning_note(
            state.get("planning_note") or latest_plan.get("planning_note"),
            state.get("material_note"),
        )
        draft_payload = {
            "planning_note": planning_note,
            "course_name": str(latest_plan.get("course_name") or ""),
            "course_icon": str(latest_plan.get("course_icon") or ""),
            **parsed,
            "build_constraints": {},
        }
        material_context = state["material_context"]
        digest_mode = state.get("digest_mode") or latest_plan.get("digest_mode") or material_context.course_mode_decision.mode.value
        effective_request_text = compose_effective_planner_request_text(
            state.get("user_prompt") or latest_plan.get("user_prompt") or "",
            state.get("feedback_message") or "",
        )
        normalized_draft = normalize_planner_draft(
            draft_payload,
            course_id=state["course_id"],
            user_prompt=effective_request_text,
            requested_digest_mode=digest_mode,
            shared_inputs=material_context,
            latest_plan=latest_plan or None,
        )
        draft_payload = normalized_draft.model_dump(mode="json")
        await emit_planner_event(
            state,
            event="planner.plan.ready",
            detail=f"方案已生成：{len(draft_payload.get('chapters') or [])} 个章节。",
            payload={
                "chapter_count": len(draft_payload.get("chapters") or []),
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
            "plan_outline_markdown": str(draft_payload.get("plan") or ""),
        }

    return compose_planner_draft_node


__all__ = [
    "_parse_diagnosis_response",
    "_parse_planner_response",
    "build_compose_planner_draft_node",
]
