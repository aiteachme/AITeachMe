"""Compose a planner draft and stream the user-visible plan text."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
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
from app.workflows.digest.planner.lib.requested_structure import resolve_planner_revision_feedback
from app.workflows.digest.planner.nodes.generate_course_identity import _clean_course_name
from app.workflows.digest.planner.prompts.build_plan_composer import (
    BUILD_CONSTRAINTS_END,
    BUILD_CONSTRAINTS_START,
    CHAPTERS_END,
    CHAPTERS_START,
    COURSE_NAME_END,
    COURSE_NAME_START,
    DIAGNOSE_END,
    DIAGNOSE_START,
    PLAN_END,
    PLAN_START,
    SUGGESTION_END,
    SUGGESTION_START,
    build_planner_diagnosis_messages,
    build_planner_diagnosis_repair_messages,
    build_planner_repair_messages,
    build_planner_stream_messages,
)
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.support.courses.icons import infer_course_icon_key, normalize_course_icon_key

logger = structlog.get_logger(__name__)


def _planner_attempt_callback(state: BuildPlannerState):
    async def emit(event: str, payload: Mapping[str, Any]) -> None:
        event_details = {
            "connecting": ("planner.llm.connecting", "正在连接模型服务。"),
            "retrying": ("planner.llm.retrying", "模型服务暂时无响应，正在重试。"),
            "fallback": ("planner.llm.fallback", "主模型服务连接失败，正在切换备用服务。"),
        }
        mapped = event_details.get(event)
        if mapped is None:
            return
        planner_event, detail = mapped
        if event == "connecting" and payload.get("endpoint_role") == "fallback":
            detail = "正在连接备用模型服务。"
        await emit_planner_event(
            state,
            event=planner_event,
            detail=detail,
            payload=dict(payload),
        )

    return emit


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


def _diagnosis_stream_preview(text: str) -> str:
    """Render only stable, user-readable fields from the diagnosis protocol."""

    if COURSE_NAME_END not in text:
        return ""
    try:
        course_name = _clean_course_name(_extract_between(text, COURSE_NAME_START, COURSE_NAME_END))
    except ValueError:
        return ""
    if not course_name:
        return ""

    questions: list[str] = []
    diagnose_start = text.find(DIAGNOSE_START)
    if diagnose_start >= 0:
        diagnose_text = text[diagnose_start + len(DIAGNOSE_START) :]
        for match in re.finditer(r'"question"\s*:\s*"(?P<question>(?:\\.|[^"\\])*)"', diagnose_text):
            question = _decode_json_string_fragment(match.group("question"))
            if question and question not in questions:
                questions.append(question)

    preview = f"正在为「{course_name}」准备前置诊断"
    if questions:
        preview += "\n\n" + "\n".join(f"{index}. {question}" for index, question in enumerate(questions, start=1))
    return preview


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
        if "}" not in segment:
            continue
        objective_match = re.search(
            r'"objective"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"',
            segment,
        )
        elements_match = re.search(
            r'"required_elements"\s*:\s*\[(?P<items>.*?)(?:\]|$)',
            segment,
            re.S,
        )
        required_elements: list[str] = []
        if elements_match:
            required_elements = _string_list(
                [
                    _decode_json_string_fragment(item.group("value"))
                    for item in re.finditer(
                        r'"(?P<value>(?:\\.|[^"\\])*)"',
                        elements_match.group("items"),
                    )
                ]
            )
        objective = (
            _decode_json_string_fragment(objective_match.group("value"))
            if objective_match
            else ""
        )
        if not objective or not required_elements:
            continue
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": title,
                "objective": objective,
                "required_elements": required_elements,
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
        objective = _clean_text(raw.get("objective"))
        required_elements = _string_list(raw.get("required_elements"))
        if not title:
            raise ValueError(f"chapter #{index} is missing title")
        if not objective:
            raise ValueError(f"chapter `{title}` is missing objective")
        if not required_elements:
            raise ValueError(f"chapter `{title}` is missing required_elements")
        chapters.append(
            {
                "chapter_index": index,
                "title": title,
                "objective": objective,
                "required_elements": required_elements,
            }
        )
    return chapters


def _parse_diagnose(value: str) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"diagnose json invalid: {exc}") from exc
    if not isinstance(decoded, list):
        raise ValueError("diagnose must be a JSON array")
    if len(decoded) != 4:
        raise ValueError("diagnose must contain exactly four questions")
    diagnose: list[dict[str, Any]] = []
    for index, raw in enumerate(decoded, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"diagnose question #{index} must be an object")
        question = _clean_text(raw.get("question") or raw.get("title") or raw.get("prompt"))
        purpose = _clean_text(raw.get("purpose") or raw.get("diagnosis_target") or raw.get("target"))
        options = _string_list(raw.get("options") or raw.get("choices"))
        if not question:
            raise ValueError(f"diagnose question #{index} is missing question")
        if not purpose:
            raise ValueError(f"diagnose question `{question}` is missing purpose")
        if not purpose.startswith("文档落点："):
            raise ValueError(f"diagnose question `{question}` purpose must start with 文档落点：")
        if len(options) != 4:
            raise ValueError(f"diagnose question `{question}` must contain four distinct options")
        if any(len(option) > 48 for option in options):
            raise ValueError(f"diagnose question `{question}` contains an option longer than 48 characters")
        if any("｜" not in option and "|" not in option for option in options):
            raise ValueError(
                f"diagnose question `{question}` options must use label｜impact format"
            )
        diagnose.append(
            {
                "question": question,
                "purpose": purpose,
                "options": options,
                "answer": "",
            }
        )
    return diagnose


def _parse_build_constraints(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"build constraints json invalid: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("build constraints must be a JSON object")
    profile = _clean_text(decoded.get("chapter_length_profile")).casefold()
    if profile not in {"outline", "standard", "detailed", "foundation"}:
        raise ValueError("chapter_length_profile must be outline, standard, detailed or foundation")
    values: dict[str, int] = {}
    for key in ("chapter_min_words", "chapter_target_words", "chapter_max_words"):
        try:
            parsed = int(decoded.get(key) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be an integer") from exc
        if not 800 <= parsed <= 8000:
            raise ValueError(f"{key} must be between 800 and 8000")
        values[key] = parsed
    if not values["chapter_min_words"] <= values["chapter_target_words"] <= values["chapter_max_words"]:
        raise ValueError("chapter word constraints must satisfy min <= target <= max")
    return {"chapter_length_profile": profile, **values}


def _parse_planner_response(text: str) -> dict[str, Any]:
    course_name = _parse_generated_course_name(text)
    plan = _clean_text(_extract_between(text, PLAN_START, PLAN_END))
    suggestion = _clean_text(_extract_between(text, SUGGESTION_START, SUGGESTION_END))
    if BUILD_CONSTRAINTS_START in text and BUILD_CONSTRAINTS_END in text:
        build_constraints = _parse_build_constraints(
            _extract_between(text, BUILD_CONSTRAINTS_START, BUILD_CONSTRAINTS_END)
        )
    else:
        # Backward-compatible default for older gateways or saved responses.
        # The current prompt emits the explicit contract so answered diagnosis
        # choices still control this value in normal runs.
        build_constraints = {
            "chapter_length_profile": "standard",
            "chapter_min_words": 2400,
            "chapter_target_words": 3000,
            "chapter_max_words": 3600,
        }
    chapters = _parse_chapters(_extract_between(text, CHAPTERS_START, CHAPTERS_END))
    if not plan:
        raise ValueError("planner response is missing plan")
    if not suggestion:
        raise ValueError("planner response is missing suggestion")
    return {
        "course_name": course_name,
        "suggestion": suggestion,
        "plan": plan,
        "diagnose": [],
        "chapters": chapters,
        "build_constraints": build_constraints,
    }


def _parse_diagnosis_response(text: str) -> list[dict[str, Any]]:
    diagnose = _parse_diagnose(_extract_between(text, DIAGNOSE_START, DIAGNOSE_END))
    if len(diagnose) != 4:
        raise ValueError("planner diagnosis response must contain four valid choice questions")
    return diagnose


def _parse_generated_course_name(text: str) -> str:
    course_name = _clean_course_name(_extract_between(text, COURSE_NAME_START, COURSE_NAME_END))
    if not course_name:
        raise ValueError("planner diagnosis response is missing a valid course name")
    return course_name


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
        "user_prompt": payload.get("user_prompt") or state.get("user_prompt") or latest_plan.get("user_prompt") or "",
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


def _normalize_generated_plan(state: BuildPlannerState, parsed: dict[str, Any]) -> dict[str, Any]:
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
    }
    material_context = state["material_context"]
    digest_mode = (
        state.get("digest_mode")
        or latest_plan.get("digest_mode")
        or material_context.course_mode_decision.mode.value
    )
    effective_request_text = compose_effective_planner_request_text(
        state.get("user_prompt") or latest_plan.get("user_prompt") or "",
        state.get("feedback_message") or "",
    )
    return normalize_planner_draft(
        draft_payload,
        course_id=state["course_id"],
        user_prompt=effective_request_text,
        requested_digest_mode=digest_mode,
        shared_inputs=material_context,
        latest_plan=latest_plan or None,
        revision_feedback=resolve_planner_revision_feedback(
            state.get("feedback_message"),
            list(state.get("message_history") or []),
            latest_plan=latest_plan or None,
        ),
    ).model_dump(mode="json")


def _planner_stream_messages(state: BuildPlannerState) -> list[dict[str, str]]:
    material_context = state["material_context"]
    latest_plan = _latest_plan_with_current_diagnosis(state, dict(state.get("latest_plan") or {}))
    planning_note = str(state.get("planning_note") or latest_plan.get("planning_note") or "").strip()
    material_note = str(state.get("material_note") or "").strip()
    return build_planner_stream_messages(
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


async def _stream_planner_response(
    state: BuildPlannerState,
    *,
    messages: list[dict[str, str]] | None = None,
) -> str:
    messages = messages or _planner_stream_messages(state)
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
        attempt_callback=_planner_attempt_callback(state),
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


async def _repair_planner_response(
    state: BuildPlannerState,
    *,
    original_messages: list[dict[str, str]],
    invalid_output: str,
    error: Exception,
) -> str:
    repaired = await acompletion_with_fallback(
        build_planner_repair_messages(
            original_messages=original_messages,
            invalid_output=invalid_output,
            error=str(error),
        ),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.REPAIR_PLAN,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="修复方案输出合同",
            initial_error_type=type(error).__name__,
        ),
    )
    if not isinstance(repaired, str) or not repaired.strip():
        raise ValueError("planner repair returned empty output")
    return repaired.strip()


async def _repair_diagnosis_response(
    state: BuildPlannerState,
    *,
    original_messages: list[dict[str, str]],
    invalid_output: str,
    error: Exception,
) -> str:
    repaired = await acompletion_with_fallback(
        build_planner_diagnosis_repair_messages(
            original_messages=original_messages,
            invalid_output=invalid_output,
            error=str(error),
        ),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.REPAIR_DIAGNOSIS,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="修复前置诊断输出合同",
            initial_error_type=type(error).__name__,
        ),
    )
    if not isinstance(repaired, str) or not repaired.strip():
        raise ValueError("planner diagnosis repair returned empty output")
    return repaired.strip()


def _should_generate_diagnosis_first(state: BuildPlannerState) -> bool:
    operation = _clean_text(state.get("planner_operation")).casefold()
    if operation == "append" and bool(state.get("refresh_diagnosis")):
        return True
    if operation != "create":
        return False
    if _clean_text(state.get("diagnose_status")):
        return False
    latest_plan = state.get("latest_plan")
    return not isinstance(latest_plan, dict) or not latest_plan


async def _stream_diagnosis_response(
    state: BuildPlannerState,
    *,
    messages: list[dict[str, str]],
) -> str:
    await emit_planner_event(
        state,
        event="planner.diagnose.started",
        detail="正在结合课程目标和资料生成前置诊断。",
    )
    raw_tokens: list[str] = []
    emitted_preview_chars = 0
    stream = acompletion_stream(
        messages,
        attempt_callback=_planner_attempt_callback(state),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.DIAGNOSE_QUESTIONS,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="生成个性化前置诊断",
        ),
    )
    async for token in stream:
        raw_tokens.append(token)
        visible_preview = _diagnosis_stream_preview("".join(raw_tokens))
        if len(visible_preview) > emitted_preview_chars:
            await emit_planner_token(state, visible_preview[emitted_preview_chars:])
            emitted_preview_chars = len(visible_preview)
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
            raw_output = ""
            try:
                material_context = state["material_context"]
                latest_plan = dict(state.get("latest_plan") or {})
                effective_request_text = compose_effective_planner_request_text(
                    state.get("user_prompt") or latest_plan.get("user_prompt") or "",
                    state.get("feedback_message") or "",
                )
                diagnosis_messages = build_planner_diagnosis_messages(
                    course_name=_course_for_prompt(state),
                    user_prompt=effective_request_text,
                    digest_mode=(
                        state.get("digest_mode")
                        or latest_plan.get("digest_mode")
                        or material_context.course_mode_decision.mode.value
                    ),
                    material_context=material_context,
                    planning_note=str(
                        state.get("planning_note") or latest_plan.get("planning_note") or ""
                    ).strip(),
                    material_note=str(state.get("material_note") or "").strip(),
                    message_history=list(state.get("message_history", [])),
                )
                raw_output = await _stream_diagnosis_response(state, messages=diagnosis_messages)
                try:
                    generated_course_name = _parse_generated_course_name(raw_output)
                    diagnose_questions = _parse_diagnosis_response(raw_output)
                except Exception as initial_error:
                    await emit_planner_event(
                        state,
                        event="planner.diagnose.repairing",
                        detail="前置诊断结构未满足要求，正在重新整理。",
                        payload={"error_type": type(initial_error).__name__},
                    )
                    repaired_output = await _repair_diagnosis_response(
                        state,
                        original_messages=diagnosis_messages,
                        invalid_output=raw_output,
                        error=initial_error,
                    )
                    generated_course_name = _parse_generated_course_name(repaired_output)
                    diagnose_questions = _parse_diagnosis_response(repaired_output)
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
                "course_name": generated_course_name,
                "course_icon": normalize_course_icon_key(infer_course_icon_key(generated_course_name)),
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
                user_prompt=effective_request_text,
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
                "generated_course_name": generated_course_name,
                "generated_course_icon_key": str(draft_payload.get("course_icon") or ""),
                "plan_outline_markdown": "",
            }

        original_messages = _planner_stream_messages(state)
        raw_output = ""
        try:
            raw_output = await _stream_planner_response(state, messages=original_messages)
            try:
                draft_payload = _normalize_generated_plan(state, _parse_planner_response(raw_output))
            except Exception as initial_error:
                await emit_planner_event(
                    state,
                    event="planner.plan.repairing",
                    detail="方案结构未满足用户要求，正在重新整理。",
                    payload={"error_type": type(initial_error).__name__},
                )
                repaired_output = await _repair_planner_response(
                    state,
                    original_messages=original_messages,
                    invalid_output=raw_output,
                    error=initial_error,
                )
                draft_payload = _normalize_generated_plan(
                    state,
                    _parse_planner_response(repaired_output),
                )
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
            plan_chars=len(str(draft_payload.get("plan") or "")),
            suggestion_chars=len(str(draft_payload.get("suggestion") or "")),
            chapter_count=len(draft_payload.get("chapters") or []),
        )
        return {
            "build_plan_draft": draft_payload,
            "plan_outline_markdown": str(draft_payload.get("plan") or ""),
        }

    return compose_planner_draft_node


__all__ = [
    "_parse_diagnosis_response",
    "_parse_generated_course_name",
    "_parse_planner_response",
    "build_compose_planner_draft_node",
]
