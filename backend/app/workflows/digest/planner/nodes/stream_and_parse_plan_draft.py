"""Generate a visible plan outline and structured draft in parallel."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from pydantic import BaseModel, Field, field_validator, model_validator

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
    build_plan_structured_count_retry_messages,
    build_plan_structured_messages,
    build_plan_visible_messages,
)
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _course_for_prompt(state: BuildPlannerState) -> str:
    material_context = state["material_context"]
    return _resolve_course_name(
        state["course_id"],
        shared_inputs=material_context,
        user_prompt=state.get("user_prompt") or "",
    )


class PlannerChapterSketch(BaseModel):
    title: str = Field(..., min_length=1)
    key_points: list[str] = Field(..., min_length=1)

    @field_validator("title", mode="before")
    @classmethod
    def _coerce_title(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("key_points", mode="before")
    @classmethod
    def _coerce_key_points(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @model_validator(mode="after")
    def _require_content(self) -> "PlannerChapterSketch":
        if not self.title.strip():
            raise ValueError("planner outline chapter is missing title")
        if not [item for item in self.key_points if item.strip()]:
            raise ValueError(f"planner outline chapter `{self.title}` is missing key_points")
        return self


class PlannerOutlineSketch(BaseModel):
    plan_text: str = Field(..., min_length=1)
    plan_steps: list[str] = Field(default_factory=list)
    chapters: list[PlannerChapterSketch] = Field(..., min_length=1)

    @field_validator("plan_text", mode="before")
    @classmethod
    def _coerce_plan_text(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("plan_steps", mode="before")
    @classmethod
    def _coerce_plan_steps(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @model_validator(mode="after")
    def _require_outline(self) -> "PlannerOutlineSketch":
        if not self.plan_text.strip():
            raise ValueError("planner outline is missing plan_text")
        if not self.chapters:
            raise ValueError("planner outline is missing chapters")
        return self


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


def _adjustment_questions_from_intent(plan_intent: PlanIntent) -> list[str]:
    return _coerce_string_list(plan_intent.adjustment_options)[:4]


def _sketch_to_plan_payload(sketch: PlannerOutlineSketch, *, plan_intent: PlanIntent) -> dict[str, Any]:
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
    build_constraints: dict[str, Any] = {}
    requested_chapter_count = _requested_chapter_count(plan_intent)
    if requested_chapter_count is not None:
        build_constraints["requested_chapter_count"] = requested_chapter_count
        build_constraints["target_chapter_count"] = requested_chapter_count
        build_constraints["chapter_count_source"] = "user_request"
    return {
        "plan_summary": sketch.plan_text.strip(),
        "plan_steps": [item.strip() for item in sketch.plan_steps if item.strip()],
        "adjustment_questions": _adjustment_questions_from_intent(plan_intent),
        "build_constraints": build_constraints,
        "chapter_plan": chapters,
    }


def _validate_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not str(payload.get("plan_summary") or "").strip():
        raise ValueError("planner outline is missing plan_text")
    if not list(payload.get("chapter_plan") or []):
        raise ValueError("planner outline is missing chapters")
    return payload


def _plan_preview_payload(state: BuildPlannerState, plan_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "course_id": state.get("course_id", ""),
        "selected_file_ids": list(state.get("selected_file_ids") or state.get("requested_file_ids") or []),
        "user_prompt": state.get("user_prompt") or "",
        "digest_mode": state.get("digest_mode") or "systematic",
        "chapter_plan": list(plan_payload.get("chapter_plan") or []),
        "build_constraints": dict(plan_payload.get("build_constraints") or {}),
        "plan_summary": str(plan_payload.get("plan_summary") or ""),
        "plan_steps": [str(item).strip() for item in list(plan_payload.get("plan_steps") or []) if str(item).strip()],
        "adjustment_questions": [
            str(item).strip()
            for item in list(plan_payload.get("adjustment_questions") or [])
            if str(item).strip()
        ],
        "status": "planning",
        "planner_session_id": state.get("planner_session_id") or None,
        "confirmed_plan_id": None,
        "model_override": state.get("model_override"),
    }


def _requested_chapter_count(plan_intent: PlanIntent) -> int | None:
    count = plan_intent.requested_chapter_count
    return count if isinstance(count, int) and count > 0 else None


async def _stream_visible_plan_response(
    state: BuildPlannerState,
    *,
    material_context,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
) -> str:
    """流式生成用户可见计划说明，机器大纲由结构化调用并行生成。"""

    tokens: list[str] = []
    try:
        await emit_planner_token(state, "\n\n")
        await emit_planner_event(
            state,
            event="planner.plan.visible_started",
            detail="正在把范围判断写成用户可见的方案说明...",
            payload={
                "target_scope": plan_intent.target_scope.strip(),
            },
        )
        logger.info(
            "planner_visible_plan_llm_starting",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id", ""),
            material_digest_chars=len(material_context.material_digest or ""),
            brief_chars=len(planner_brief.markdown or ""),
            query_count=len(plan_intent.plan_queries),
        )
        stream = acompletion_stream(
            build_plan_visible_messages(
                course_name=_course_for_prompt(state),
                user_prompt=state.get("user_prompt") or "",
                digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                material_context=material_context,
                planner_brief=planner_brief,
                plan_intent=plan_intent,
                message_history=list(state.get("message_history", [])),
                latest_feedback=state.get("feedback_message") or "",
                latest_plan=state.get("latest_plan"),
                existing_doc_context=state.get("existing_doc_context"),
                planner_context_mode=state.get("planner_context_mode") or "fresh_build",
            ),
            **planner_completion_kwargs_with_metadata(
                PlannerModelStep.VISIBLE_PLAN,
                model_override=state.get("model_override"),
                planner_session_id=state.get("planner_session_id") or "",
                substep="流式生成计划说明",
            ),
        )
        async for token in stream:
            tokens.append(token)
            await emit_planner_token(state, token)
    except Exception:
        logger.exception(
            "planner_composer_stream_failed",
            planner_session_id=state.get("planner_session_id") or "",
            course_id=state.get("course_id") or "",
        )
        raise
    text = "".join(tokens).strip()
    logger.info(
        "planner_visible_plan_llm_completed",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id", ""),
        token_count=len(tokens),
        response_chars=len(text),
    )
    await emit_planner_event(
        state,
        event="planner.plan.visible_ready",
        detail="计划说明已生成，正在等待结构化大纲校验。",
        payload={
            "target_scope": plan_intent.target_scope.strip(),
            "response_chars": len(text),
        },
    )
    return text


async def _retry_outline_for_requested_count(
    state: BuildPlannerState,
    *,
    material_context,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
    previous_sketch: PlannerOutlineSketch,
    required_chapter_count: int,
) -> PlannerOutlineSketch:
    await emit_planner_event(
        state,
        event="planner.plan.structure_retrying",
        detail=f"结构化大纲章数与用户指定不一致，正在重新生成 {required_chapter_count} 章。",
        payload={
            "target_scope": plan_intent.target_scope.strip(),
            "required_chapter_count": required_chapter_count,
            "previous_chapter_count": len(previous_sketch.chapters),
        },
    )
    result = await acompletion_with_fallback(
        build_plan_structured_count_retry_messages(
            course_name=_course_for_prompt(state),
            user_prompt=state.get("user_prompt") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            material_context=material_context,
            planner_brief=planner_brief,
            plan_intent=plan_intent,
            previous_outline=previous_sketch.model_dump(mode="json"),
            required_chapter_count=required_chapter_count,
            message_history=list(state.get("message_history", [])),
            latest_feedback=state.get("feedback_message") or "",
            latest_plan=state.get("latest_plan"),
            existing_doc_context=state.get("existing_doc_context"),
            planner_context_mode=state.get("planner_context_mode") or "fresh_build",
        ),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.STRUCTURED_PLAN,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="按用户指定章数重生成计划大纲",
            repair_reason="requested_chapter_count_mismatch",
        ),
        response_model=PlannerOutlineSketch,
    )
    return result if isinstance(result, PlannerOutlineSketch) else PlannerOutlineSketch.model_validate(result)


async def _compose_outline_sketch_with_llm(
    state: BuildPlannerState,
    *,
    material_context,
    planner_brief: PlannerBrief,
    plan_intent: PlanIntent,
) -> PlannerOutlineSketch:
    """Generate the machine-readable planner outline through structured output."""

    logger.info(
        "planner_structured_outline_llm_starting",
        planner_session_id=state.get("planner_session_id") or "",
        course_id=state.get("course_id") or "",
        material_digest_chars=len(material_context.material_digest or ""),
        brief_chars=len(planner_brief.markdown or ""),
        query_count=len(plan_intent.plan_queries),
    )
    await emit_planner_event(
        state,
        event="planner.plan.structure_started",
        detail=(
            f"正在围绕“{plan_intent.target_scope.strip()}”梳理可确认学习大纲..."
            if plan_intent.target_scope.strip()
            else "正在梳理可确认学习大纲..."
        ),
        payload={
            "target_scope": plan_intent.target_scope.strip(),
            "query_count": len(plan_intent.plan_queries),
        },
    )
    result = await acompletion_with_fallback(
        build_plan_structured_messages(
            course_name=_course_for_prompt(state),
            user_prompt=state.get("user_prompt") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            material_context=material_context,
            planner_brief=planner_brief,
            plan_intent=plan_intent,
            message_history=list(state.get("message_history", [])),
            latest_feedback=state.get("feedback_message") or "",
            latest_plan=state.get("latest_plan"),
            existing_doc_context=state.get("existing_doc_context"),
            planner_context_mode=state.get("planner_context_mode") or "fresh_build",
        ),
        **planner_completion_kwargs_with_metadata(
            PlannerModelStep.STRUCTURED_PLAN,
            model_override=state.get("model_override"),
            planner_session_id=state.get("planner_session_id") or "",
            substep="结构化生成计划大纲",
        ),
        response_model=PlannerOutlineSketch,
    )
    sketch = result if isinstance(result, PlannerOutlineSketch) else PlannerOutlineSketch.model_validate(result)
    required_chapter_count = _requested_chapter_count(plan_intent)
    if required_chapter_count is not None and len(sketch.chapters) != required_chapter_count:
        sketch = await _retry_outline_for_requested_count(
            state,
            material_context=material_context,
            planner_brief=planner_brief,
            plan_intent=plan_intent,
            previous_sketch=sketch,
            required_chapter_count=required_chapter_count,
        )
    if required_chapter_count is not None and len(sketch.chapters) != required_chapter_count:
        raise ValueError(
            f"planner outline chapter count {len(sketch.chapters)} does not match requested {required_chapter_count}"
        )
    logger.info(
        "planner_structured_outline_llm_completed",
        planner_session_id=state.get("planner_session_id") or "",
        plan_text_chars=len(sketch.plan_text or ""),
        plan_step_count=len(sketch.plan_steps),
        adjustment_question_count=len(_adjustment_questions_from_intent(plan_intent)),
        chapter_count=len(sketch.chapters),
    )
    plan_payload = _validate_plan_payload(_sketch_to_plan_payload(sketch, plan_intent=plan_intent))
    await emit_planner_event(
        state,
        event="planner.plan.structure_ready",
        detail=(
            f"结构化大纲已通过校验：{len(sketch.chapters)} 章，"
            f"{len(_adjustment_questions_from_intent(plan_intent))} 个可调整问题。"
        ),
        payload={
            "target_scope": plan_intent.target_scope.strip(),
            "chapter_count": len(sketch.chapters),
            "adjustment_question_count": len(_adjustment_questions_from_intent(plan_intent)),
            "chapter_titles": [chapter.title.strip() for chapter in sketch.chapters if chapter.title.strip()][:6],
            "plan_preview": _plan_preview_payload(state, plan_payload),
        },
    )
    return sketch


def build_stream_and_parse_plan_draft_node(*, context: WorkflowContext):
    """构建计划合成节点。

    负责并行调用模型生成用户可见计划说明和结构化机器大纲，并把结果
    转成待 normalize 的 planner draft。
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
        visible_task: asyncio.Task[str] | None = None
        sketch_task: asyncio.Task[PlannerOutlineSketch] | None = None
        try:
            visible_task = asyncio.create_task(
                _stream_visible_plan_response(
                    state,
                    material_context=material_context,
                    planner_brief=planner_brief,
                    plan_intent=plan_intent,
                )
            )
            sketch_task = asyncio.create_task(
                _compose_outline_sketch_with_llm(
                    state,
                    material_context=material_context,
                    planner_brief=planner_brief,
                    plan_intent=plan_intent,
                )
            )
            visible_outline, sketch = await asyncio.gather(visible_task, sketch_task)
            draft_payload = _validate_plan_payload(_sketch_to_plan_payload(sketch, plan_intent=plan_intent))
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
                "planner_structured_outline_failed",
                planner_session_id=state.get("planner_session_id") or "",
                course_id=state.get("course_id") or "",
                error=str(exc),
            )
            for task in (visible_task, sketch_task):
                if task is not None and not task.done():
                    task.cancel()
            pending_tasks = [task for task in (visible_task, sketch_task) if task is not None]
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            await emit_planner_event(
                state,
                event="planner.plan.failed",
                detail="模型返回的计划结构不完整，结构化输出校验失败，请重试或调整学习目标。",
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
