"""Stream the visible plan outline and parse its hidden JSON draft."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from pydantic import BaseModel, Field

from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import build_fallback_plan
from app.workflows.digest.planner.lib.models import LearningIntent, PlannerBrief
from app.workflows.digest.planner.prompts import PLAN_JSON_END_MARKER, PLAN_JSON_MARKER, build_plan_composer_messages
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class PlannerChapterSketch(BaseModel):
    title: str = ""
    key_points: list[str] = Field(default_factory=list)


class PlannerOutlineSketch(BaseModel):
    plan_text: str = ""
    chapters: list[PlannerChapterSketch] = Field(default_factory=list)


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
        if not title and not key_points:
            continue
        chapters.append(
            {
                "chapter_index": index,
                "title": title or f"第 {index} 章",
                "objective": "；".join(key_points),
                "required_elements": key_points,
                "search_queries": [],
                "writing_instructions": "围绕本章知识点生成清晰讲解。",
                "media_hints": {"images": [], "mermaid": [], "interactive": []},
            }
        )
    return {
        "plan_summary": sketch.plan_text.strip(),
        "chapter_plan": chapters,
        "research_queries": [],
    }


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
    intent: LearningIntent,
) -> str:
    tokens: list[str] = []
    pending_visible = ""
    visible_closed = False
    try:
        await emit_planner_token(state, "\n\n")
        stream = acompletion_stream(
            build_plan_composer_messages(
                subject=state["subject"],
                user_goal=state.get("user_goal") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                tone=state.get("tone") or "encouraging",
                material_context=material_context,
                planner_brief=planner_brief,
                learning_intent=intent,
                message_history=list(state.get("message_history", [])),
                latest_plan=state.get("latest_plan"),
            ),
            task_type=TaskType.REASONING,
            model="reason",
            temperature=0.15,
            max_tokens=3200,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "stream_and_parse_plan_draft",
            },
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
            else:
                holdback = _marker_holdback_length(pending_visible, PLAN_JSON_MARKER)
                safe_length = len(pending_visible) - holdback
                safe_text = pending_visible[:safe_length]
                pending_visible = pending_visible[safe_length:]
            if safe_text:
                await emit_planner_token(state, safe_text)
                await emit_planner_event(
                    state,
                    event="planner.plan.delta",
                    detail="计划大纲生成中...",
                    payload={"token": safe_text},
                )
    except Exception:
        logger.exception(
            "planner_composer_stream_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject") or "",
        )
        return ""
    if pending_visible and not visible_closed:
        await emit_planner_token(state, pending_visible)
        await emit_planner_event(
            state,
            event="planner.plan.delta",
            detail="计划大纲生成中...",
            payload={"token": pending_visible},
        )
    return "".join(tokens).strip()


def build_stream_and_parse_plan_draft_node(*, context: WorkflowContext):
    del context

    async def stream_and_parse_plan_draft_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        planner_brief = PlannerBrief.model_validate(state.get("planner_brief") or {})
        intent = LearningIntent.model_validate(state.get("learning_intent") or {})
        fallback = build_fallback_plan(
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            tone=state.get("tone") or "encouraging",
            shared_inputs=material_context,
        )
        await emit_planner_event(
            state,
            event="planner.plan.composing",
            detail="正在把思考过程提炼成几条可确认的计划大纲...",
        )
        raw_response = await _stream_composer_response(
            state,
            material_context=material_context,
            planner_brief=planner_brief,
            intent=intent,
        )
        visible_outline = _visible_outline_from_response(raw_response)
        try:
            sketch = _parse_outline_sketch(raw_response)
            draft_payload = _sketch_to_plan_payload(sketch)
        except Exception:
            logger.exception(
                "planner_composer_parse_failed",
                planner_session_id=state.get("planner_session_id") or "",
                subject=state.get("subject") or "",
            )
            await emit_planner_event(
                state,
                event="planner.fallback.used",
                detail="最终大纲合成解析失败，已使用规则构建方案继续。",
            )
            draft_payload = fallback.model_dump(mode="json")
        return {
            "build_plan_draft": draft_payload,
            "plan_outline_markdown": visible_outline,
            "generation_mode": "raw_context_three_call_no_retrieval_v6",
        }

    return stream_and_parse_plan_draft_node


__all__ = ["build_stream_and_parse_plan_draft_node"]
