"""Stream the visible plan outline and parse its hidden JSON draft."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from pydantic import BaseModel, Field, field_validator

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.model_policy import (
    PlannerModelStep,
    planner_completion_kwargs_with_metadata,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.models import PlanIntent, PlannerBrief
from app.workflows.digest.planner.lib.plans import _resolve_course_name
from app.workflows.digest.planner.prompts.build_plan_composer import (
    PLAN_JSON_END_MARKER,
    PLAN_JSON_MARKER,
    build_plan_composer_messages,
    build_plan_outline_repair_messages,
)
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _course_for_prompt(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    return _resolve_course_name(
        state["course_id"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


class PlannerChapterSketch(BaseModel):
    title: str = ""
    key_points: list[str] = Field(default_factory=list)

    @field_validator("key_points", mode="before")
    @classmethod
    def _coerce_key_points(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class PlannerOutlineSketch(BaseModel):
    plan_text: str = ""
    plan_steps: list[str] = Field(default_factory=list)
    chapters: list[PlannerChapterSketch] = Field(default_factory=list)

    @field_validator("plan_steps", mode="before")
    @classmethod
    def _coerce_plan_steps(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


def _clean_text(value: Any, *, max_chars: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _coerce_string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[\n,，;；、]+", value)
    elif isinstance(value, dict):
        raw_items = value.values()
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _clean_text(item)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _marker_holdback_length(text: str, marker: str) -> int:
    """Hold back a possible partial marker so JSON tags never leak to SSE."""

    max_length = min(len(text), len(marker) - 1)
    for length in range(max_length, 0, -1):
        if marker.startswith(text[-length:]):
            return length
    return 0


def _extract_plan_json(raw_text: str) -> str:
    """Extract the BuildPlannerDraft JSON block from one streamed response."""

    text = (raw_text or "").strip()
    if PLAN_JSON_MARKER in text:
        text = text.split(PLAN_JSON_MARKER, 1)[1]
    if PLAN_JSON_END_MARKER in text:
        text = text.split(PLAN_JSON_END_MARKER, 1)[0]

    for match in _JSON_FENCE_RE.finditer(text):
        fenced = match.group(1).strip()
        if fenced:
            return fenced

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end >= start:
        return text[start : end + 1]
    raise ValueError("composer response did not contain a JSON object")


def _parse_outline_sketch(raw_text: str) -> PlannerOutlineSketch:
    payload = json.loads(_extract_plan_json(raw_text))
    return PlannerOutlineSketch.model_validate(payload)


def _sketch_to_plan_payload(sketch: PlannerOutlineSketch) -> dict[str, Any]:
    chapters: list[dict[str, Any]] = []
    for index, chapter in enumerate(sketch.chapters, start=1):
        title = chapter.title.strip()
        key_points = [item.strip() for item in chapter.key_points if item.strip()]
        if not title:
            raise ValueError(f"planner outline chapter #{index} is missing title")
        if not key_points:
            raise ValueError(f"planner outline chapter `{title}` is missing key_points")
        chapters.append(
            {
                "chapter_index": index,
                "title": title,
                "objective": "；".join(key_points),
                "required_elements": key_points,
                "writing_instructions": "围绕本章知识点生成清晰讲解。",
            }
        )
    return {
        "plan_summary": sketch.plan_text.strip(),
        "plan_steps": [item.strip() for item in sketch.plan_steps if item.strip()],
        "chapter_plan": chapters,
    }


def _validate_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not str(payload.get("plan_summary") or "").strip():
        raise ValueError("planner outline is missing plan_text")
    if not list(payload.get("chapter_plan") or []):
        raise ValueError("planner outline is missing chapters")
    return payload


def _visible_outline_from_response(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if PLAN_JSON_MARKER in text:
        text = text.split(PLAN_JSON_MARKER, 1)[0]
    return text.strip()


async def _stream_composer_response(
    state: BuildPlannerState,
    *,
    material_context,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
) -> str:
    """流式生成可见计划说明，同时隐藏机器 JSON 合同。

    前端只看到 `<PLAN_JSON>` 之前的自然语言计划说明；完整响应会保留在
    后端用于解析 plan_text / plan_steps / chapters，避免机器合同泄露到 UI。
    """

    tokens: list[str] = []
    pending_visible = ""
    visible_closed = False
    try:
        await emit_planner_token(state, "\n\n")
        logger.info(
            "planner_compose_llm_starting",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id", ""),
            material_digest_chars=len(material_context.material_digest or ""),
            brief_chars=len(planner_brief.markdown or ""),
            query_count=len(plan_intent.plan_queries),
        )
        stream = acompletion_stream(
            build_plan_composer_messages(
                course_name=_course_for_prompt(state),
                user_prompt=state.get("user_prompt") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                material_context=material_context,
                planner_brief=planner_brief,
                plan_intent=plan_intent,
                message_history=list(state.get("message_history", [])),
                latest_plan=state.get("latest_plan"),
            ),
            **planner_completion_kwargs_with_metadata(
                PlannerModelStep.COMPOSE_PLAN,
                model_override=state.get("model_override"),
                planner_session_id=state.get("planner_session_id") or "",
                substep="合成计划大纲",
            ),
        )
        async for token in stream:
            tokens.append(token)
            if visible_closed:
                continue
            pending_visible += token
            marker_index = pending_visible.find(PLAN_JSON_MARKER)
            if marker_index >= 0:
                # Everything after PLAN_JSON_MARKER is machine-only contract
                # data. Keep it in raw_response for parsing, but do not stream
                # it to the user-facing token callback.
                safe_text = pending_visible[:marker_index]
                visible_closed = True
                pending_visible = ""
                await emit_planner_event(
                    state,
                    event="planner.plan.finalizing",
                    detail="计划大纲已生成，正在校验结构并保存草稿...",
                )
            else:
                holdback = _marker_holdback_length(pending_visible, PLAN_JSON_MARKER)
                safe_length = len(pending_visible) - holdback
                safe_text = pending_visible[:safe_length]
                pending_visible = pending_visible[safe_length:]
            if safe_text:
                await emit_planner_token(state, safe_text)
    except Exception:
        logger.exception(
            "planner_composer_stream_failed",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id") or "",
        )
        raise
    if pending_visible and not visible_closed:
        await emit_planner_token(state, pending_visible)
    text = "".join(tokens).strip()
    logger.info(
        "planner_compose_llm_completed",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id", ""),
        token_count=len(tokens),
        response_chars=len(text),
        visible_closed=visible_closed,
    )
    return text


async def _repair_outline_sketch_with_llm(
    state: BuildPlannerState,
    *,
    material_context,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
    raw_response: str,
    parse_error: Exception,
) -> PlannerOutlineSketch:
    """Repair malformed composer JSON through the structured LLM path."""

    logger.warning(
        "planner_composer_parse_repair_llm_starting",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id") or "",
        error=str(parse_error),
        raw_response_chars=len(raw_response or ""),
    )
    result = await acompletion_with_fallback(
        build_plan_outline_repair_messages(
            course_name=_course_for_prompt(state),
            user_prompt=state.get("user_prompt") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            material_context=material_context,
            planner_brief=planner_brief,
            plan_intent=plan_intent,
            raw_response=raw_response,
            parse_error=str(parse_error),
            message_history=list(state.get("message_history", [])),
            latest_plan=state.get("latest_plan"),
        ),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.COMPOSE_PLAN,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="修复计划大纲结构",
            repair_reason="composer_json_parse_failed",
        ),
        response_model=PlannerOutlineSketch,
    )
    return result if isinstance(result, PlannerOutlineSketch) else PlannerOutlineSketch.model_validate(result)


def build_stream_and_parse_plan_draft_node(*, context: WorkflowContext):
    """构建计划合成节点。

    负责调用模型流式输出计划说明，解析隐藏 JSON 大纲，并把结果转成待
    normalize 的 planner draft。
    """

    del context

    async def stream_and_parse_plan_draft_node(state: BuildPlannerState) -> dict:
        """合成并解析当前 Planner 草稿。"""

        if state.get("error"):
            return {}

        logger.info(
            "planner_compose_node_started",
            planner_session_id=state.get("planner_session_id", ""),
            course_id=state.get("course_id", ""),
        )
        material_context = state["material_context"]
        planner_brief = PlannerBrief.model_validate(state.get("planner_brief") or {})
        plan_intent = PlanIntent.model_validate(state.get("plan_intent") or {})
        await emit_planner_event(
            state,
            event="planner.plan.composing",
            detail="正在生成计划说明和可调整的初步大纲...",
        )
        raw_response = await _stream_composer_response(
            state,
            material_context=material_context,
            planner_brief=planner_brief,
            plan_intent=plan_intent,
        )
        visible_outline = _visible_outline_from_response(raw_response)
        try:
            sketch = _parse_outline_sketch(raw_response)
            draft_payload = _validate_plan_payload(_sketch_to_plan_payload(sketch))
            logger.info(
                "planner_compose_parse_completed",
                planner_session_id=state.get("planner_session_id", ""),
                plan_text_chars=len(sketch.plan_text or ""),
                plan_step_count=len(sketch.plan_steps),
                chapter_count=len(sketch.chapters),
                visible_outline_chars=len(visible_outline),
            )
        except Exception as exc:
            logger.exception(
                "planner_composer_parse_failed",
                planner_session_id=state.get("planner_session_id") or "",
                course_id=state.get("course_id") or "",
            )
            try:
                sketch = await _repair_outline_sketch_with_llm(
                    state,
                    material_context=material_context,
                    planner_brief=planner_brief,
                    plan_intent=plan_intent,
                    raw_response=raw_response,
                    parse_error=exc,
                )
                draft_payload = _validate_plan_payload(_sketch_to_plan_payload(sketch))
                visible_outline = visible_outline or sketch.plan_text.strip()
                await emit_planner_event(
                    state,
                    event="planner.plan.repaired",
                    detail="模型返回结构不完整，已通过结构化模型调用修复计划大纲。",
                )
                logger.info(
                    "planner_composer_parse_repaired",
                    planner_session_id=state.get("planner_session_id") or "",
                    plan_text_chars=len(sketch.plan_text or ""),
                    plan_step_count=len(sketch.plan_steps),
                    chapter_count=len(sketch.chapters),
                )
            except Exception:
                logger.exception(
                    "planner_composer_parse_repair_failed",
                    planner_session_id=state.get("planner_session_id") or "",
                    course_id=state.get("course_id") or "",
                )
                await emit_planner_event(
                    state,
                    event="planner.plan.failed",
                    detail="模型返回结构不完整，结构化修复也失败，请重试或调整学习目标。",
                )
                raise
        result = {
            "build_plan_draft": draft_payload,
            "plan_outline_markdown": visible_outline,
        }
        logger.info(
            "planner_compose_node_completed",
            planner_session_id=state.get("planner_session_id", ""),
            chapter_count=len(draft_payload.get("chapter_plan") or []),
            plan_step_count=len(draft_payload.get("plan_steps") or []),
            plan_summary_chars=len(str(draft_payload.get("plan_summary") or "")),
        )
        return result

    return stream_and_parse_plan_draft_node


__all__ = ["build_stream_and_parse_plan_draft_node"]
