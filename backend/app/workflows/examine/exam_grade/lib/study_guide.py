"""Study-guide generation for graded exam papers."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from datetime import datetime
from time import monotonic

import structlog
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import from_json

from app.schemas.exams import ExamStudyGuideFocusUnit, ExamStudyGuideResponse
from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.observability.trace import traceable_with_context
from app.workflows.examine.exam_grade.lib.model_policy import (
    ExamGradeModelStep,
    exam_grade_completion_kwargs_with_metadata,
)
from app.workflows.examine.exam_grade.prompts import build_study_guide_messages

logger = structlog.get_logger(__name__)

STUDY_GUIDE_STRENGTH_LIMIT = 2
STUDY_GUIDE_FOCUS_UNIT_LIMIT = 3
STUDY_GUIDE_PRIORITY_GAP_LIMIT = 3
STUDY_GUIDE_ACTION_STEP_LIMIT = 3
_STREAM_SECTION_REVEAL_INTERVAL_SECONDS = 0.12
_STREAM_CONTENT_FIELDS = (
    "overall_summary",
    "strengths",
    "focus_units",
    "priority_gaps",
    "action_steps",
)

_INTERNAL_LABEL_REPLACEMENTS = {
    "forgetting_due": "已到建议复习时间",
    "repeated_wrong": "近期同类题连续出错",
    "prereq_gap": "前置知识仍有缺口",
    "newly_learned": "新学内容尚未稳定",
    "concept_confusion": "概念混淆",
    "calculation_error": "计算错误",
    "prerequisite_gap": "前置知识缺口",
    "careless_mistake": "审题或书写疏漏",
    "incomplete_understanding": "理解不完整",
    "method_misapplication": "方法使用不当",
}


def _public_study_guide_text(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    for internal_label, public_label in _INTERNAL_LABEL_REPLACEMENTS.items():
        text = text.replace(internal_label, public_label)
    return text


def _list_prefix(value: object, *, limit: int) -> object:
    if isinstance(value, (list, tuple)):
        return list(value)[:limit]
    return value


class ExamStudyGuidePayload(BaseModel):
    overall_summary: str = Field(min_length=20, max_length=1600)
    strengths: list[str] = Field(default_factory=list)
    focus_units: list[ExamStudyGuideFocusUnit] = Field(default_factory=list)
    priority_gaps: list[str] = Field(default_factory=list)
    action_steps: list[str] = Field(default_factory=list)

    @field_validator("strengths", mode="before")
    @classmethod
    def _limit_strengths(cls, value: object) -> object:
        return _list_prefix(value, limit=STUDY_GUIDE_STRENGTH_LIMIT)

    @field_validator("focus_units", mode="before")
    @classmethod
    def _limit_focus_units(cls, value: object) -> object:
        return _list_prefix(value, limit=STUDY_GUIDE_FOCUS_UNIT_LIMIT)

    @field_validator("priority_gaps", mode="before")
    @classmethod
    def _limit_priority_gaps(cls, value: object) -> object:
        return _list_prefix(value, limit=STUDY_GUIDE_PRIORITY_GAP_LIMIT)

    @field_validator("action_steps", mode="before")
    @classmethod
    def _limit_action_steps(cls, value: object) -> object:
        return _list_prefix(value, limit=STUDY_GUIDE_ACTION_STEP_LIMIT)

    @field_validator("overall_summary")
    @classmethod
    def _strip_summary(cls, value: str) -> str:
        return _public_study_guide_text(value)

    @field_validator("strengths", "priority_gaps", "action_steps")
    @classmethod
    def _normalize_str_list(cls, value: list[str]) -> list[str]:
        return [_public_study_guide_text(item) for item in value if str(item or "").strip()]

    @model_validator(mode="after")
    def _normalize_focus_unit_text(self) -> "ExamStudyGuidePayload":
        self.focus_units = [
            item.model_copy(
                update={
                    "knowledge_unit_name": _public_study_guide_text(item.knowledge_unit_name),
                    "reason": _public_study_guide_text(item.reason),
                }
            )
            for item in self.focus_units
            if _public_study_guide_text(item.knowledge_unit_name)
        ]
        return self


class ExamStudyGuideGenerationError(RuntimeError):
    """Raised when the study-guide model does not produce a usable guide."""


StudyGuideContentCallback = Callable[[ExamStudyGuideResponse], object]

_STREAM_EMIT_MIN_CHARS = 64
_STREAM_EMIT_INTERVAL_SECONDS = 0.18


def _json_object_fragment(raw: str) -> str:
    start = raw.find("{")
    if start < 0:
        return ""
    return raw[start:]


def _complete_json_object(raw: str) -> str:
    fragment = _json_object_fragment(raw)
    if not fragment:
        return ""

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(fragment):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return fragment[: index + 1]
    return ""


def _partial_string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        _public_study_guide_text(item)
        for item in value[:limit]
        if isinstance(item, str) and item
    ]


def _partial_focus_units(value: object) -> list[ExamStudyGuideFocusUnit]:
    if not isinstance(value, list):
        return []

    units: list[ExamStudyGuideFocusUnit] = []
    for item in value[:STUDY_GUIDE_FOCUS_UNIT_LIMIT]:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("knowledge_unit_id")
        knowledge_unit_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
        raw_mastery = item.get("mastery_score")
        mastery_score = (
            float(raw_mastery)
            if isinstance(raw_mastery, (int, float)) and not isinstance(raw_mastery, bool)
            else None
        )
        knowledge_unit_name = item.get("knowledge_unit_name")
        reason = item.get("reason")
        name_text = _public_study_guide_text(knowledge_unit_name) if isinstance(knowledge_unit_name, str) else ""
        reason_text = _public_study_guide_text(reason) if isinstance(reason, str) else ""
        if not name_text and not reason_text:
            continue
        units.append(
            ExamStudyGuideFocusUnit(
                knowledge_unit_id=knowledge_unit_id,
                knowledge_unit_name=name_text,
                mastery_score=mastery_score,
                reason=reason_text,
            )
        )
    return units


def _partial_study_guide_response(
    raw: str,
    *,
    exam_paper_id: int,
    course_name: str,
    generated_at: datetime,
) -> ExamStudyGuideResponse | None:
    fragment = _json_object_fragment(raw)
    if not fragment:
        return None
    try:
        payload = from_json(fragment, allow_partial="trailing-strings")
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    overall_summary = payload.get("overall_summary")
    summary_text = _public_study_guide_text(overall_summary) if isinstance(overall_summary, str) else ""
    strengths = _partial_string_list(
        payload.get("strengths"),
        limit=STUDY_GUIDE_STRENGTH_LIMIT,
    )
    focus_units = _partial_focus_units(payload.get("focus_units"))
    priority_gaps = _partial_string_list(
        payload.get("priority_gaps"),
        limit=STUDY_GUIDE_PRIORITY_GAP_LIMIT,
    )
    action_steps = _partial_string_list(
        payload.get("action_steps"),
        limit=STUDY_GUIDE_ACTION_STEP_LIMIT,
    )
    if not any((summary_text, strengths, focus_units, priority_gaps, action_steps)):
        return None

    return ExamStudyGuideResponse(
        exam_paper_id=exam_paper_id,
        course_name=course_name,
        generated_at=generated_at,
        overall_summary=summary_text,
        strengths=strengths,
        focus_units=focus_units,
        priority_gaps=priority_gaps,
        action_steps=action_steps,
        review_tasks=[],
    )


def _validated_stream_payload(raw: str) -> ExamStudyGuidePayload:
    complete = _complete_json_object(raw)
    if not complete:
        raise ValueError("streamed study guide did not contain a complete JSON object")
    return ExamStudyGuidePayload.model_validate(json.loads(complete))


async def _notify_content(
    callback: StudyGuideContentCallback | None,
    response: ExamStudyGuideResponse,
) -> None:
    if callback is None:
        return
    result = callback(response)
    if inspect.isawaitable(result):
        await result


def _ordered_stream_snapshots(
    previous: ExamStudyGuideResponse | None,
    current: ExamStudyGuideResponse,
) -> list[ExamStudyGuideResponse]:
    """Split a provider chunk into cumulative snapshots in display order."""
    working = previous or current.model_copy(
        update={
            "overall_summary": "",
            "strengths": [],
            "focus_units": [],
            "priority_gaps": [],
            "action_steps": [],
        }
    )
    snapshots: list[ExamStudyGuideResponse] = []
    for field_name in _STREAM_CONTENT_FIELDS:
        field_value = getattr(current, field_name)
        if field_value == getattr(working, field_name):
            continue
        working = working.model_copy(update={field_name: field_value})
        snapshots.append(working)
    return snapshots


def _response_from_payload(
    payload: ExamStudyGuidePayload,
    *,
    exam_paper_id: int,
    course_name: str,
    generated_at: datetime,
) -> ExamStudyGuideResponse:
    return ExamStudyGuideResponse(
        exam_paper_id=exam_paper_id,
        course_name=course_name,
        generated_at=generated_at,
        overall_summary=payload.overall_summary,
        strengths=payload.strengths,
        focus_units=payload.focus_units,
        priority_gaps=payload.priority_gaps,
        action_steps=payload.action_steps,
        review_tasks=[],
    )


@traceable_with_context(
    name="考试：学习指南生成",
    run_type="chain",
    metadata_factory=lambda **kwargs: {
        "substep": "exam.study_guide.generate",
        "exam_paper_id": kwargs.get("exam_paper_id"),
        "course_name": kwargs.get("course_name"),
        "wrong_question_count": len(kwargs.get("wrong_question_summaries") or []),
        "knowledge_unit_performance_count": len(kwargs.get("knowledge_unit_performance") or []),
        "pending_review_count": len(kwargs.get("pending_reviews") or []),
    },
    tags_factory=lambda **kwargs: [
        "exam-grade",
        "study-guide",
    ],
)
async def generate_exam_study_guide(
    *,
    exam_paper_id: int,
    course_name: str,
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, str]],
    knowledge_unit_performance: list[dict[str, object]],
    pending_reviews: list[dict[str, str]],
    generated_at: datetime,
    content_callback: StudyGuideContentCallback | None = None,
) -> ExamStudyGuideResponse:
    messages = build_study_guide_messages(
        course_name=course_name,
        exam_title=exam_title,
        score_summary=score_summary,
        wrong_question_summaries=wrong_question_summaries,
        knowledge_unit_performance=knowledge_unit_performance,
        pending_reviews=pending_reviews,
    )
    completion_kwargs = exam_grade_completion_kwargs_with_metadata(
        ExamGradeModelStep.STUDY_GUIDE,
        extra_metadata={
            "substep": "exam.study_guide",
            "course_name": course_name,
            "exam_paper_id": exam_paper_id,
        },
    )

    streamed_error: Exception | None = None
    last_published_response: ExamStudyGuideResponse | None = None

    async def publish_ordered_content(response: ExamStudyGuideResponse) -> None:
        nonlocal last_published_response
        if content_callback is None:
            return
        snapshots = _ordered_stream_snapshots(last_published_response, response)
        for index, snapshot in enumerate(snapshots):
            await _notify_content(content_callback, snapshot)
            last_published_response = snapshot
            if index < len(snapshots) - 1:
                await asyncio.sleep(_STREAM_SECTION_REVEAL_INTERVAL_SECONDS)

    if content_callback is not None:
        raw_chunks: list[str] = []
        raw_length = 0
        last_emit_length = 0
        last_emit_at = 0.0
        last_emitted_json = ""
        try:
            async for chunk in acompletion_stream(messages, **completion_kwargs):
                raw_chunks.append(chunk)
                raw_length += len(chunk)
                now = monotonic()
                if (
                    last_emit_length > 0
                    and raw_length - last_emit_length < _STREAM_EMIT_MIN_CHARS
                    and now - last_emit_at < _STREAM_EMIT_INTERVAL_SECONDS
                ):
                    continue
                partial = _partial_study_guide_response(
                    "".join(raw_chunks),
                    exam_paper_id=exam_paper_id,
                    course_name=course_name,
                    generated_at=generated_at,
                )
                if partial is None:
                    continue
                partial_json = partial.model_dump_json()
                if partial_json == last_emitted_json:
                    continue
                await publish_ordered_content(partial)
                last_emitted_json = partial_json
                last_emit_length = raw_length
                last_emit_at = now

            result = _validated_stream_payload("".join(raw_chunks))
            response = _response_from_payload(
                result,
                exam_paper_id=exam_paper_id,
                course_name=course_name,
                generated_at=generated_at,
            )
            if response.model_dump_json() != last_emitted_json:
                await publish_ordered_content(response)
            return response
        except Exception as exc:
            streamed_error = exc
            logger.warning(
                "exam_study_guide_stream_falling_back",
                exam_paper_id=exam_paper_id,
                course_name=course_name,
                error=str(exc),
            )

    try:
        result = await acompletion_with_fallback(
            messages,
            **completion_kwargs,
            response_model=ExamStudyGuidePayload,
        )
        assert isinstance(result, ExamStudyGuidePayload)
    except Exception as exc:
        stream_context = f"; streaming attempt failed first: {streamed_error}" if streamed_error else ""
        raise ExamStudyGuideGenerationError(
            f"study-guide model failed for exam_paper_id={exam_paper_id}: {exc}{stream_context}"
        ) from exc
    response = _response_from_payload(
        result,
        exam_paper_id=exam_paper_id,
        course_name=course_name,
        generated_at=generated_at,
    )
    await publish_ordered_content(response)
    return response


__all__ = [
    "ExamStudyGuideGenerationError",
    "ExamStudyGuidePayload",
    "STUDY_GUIDE_ACTION_STEP_LIMIT",
    "STUDY_GUIDE_FOCUS_UNIT_LIMIT",
    "STUDY_GUIDE_PRIORITY_GAP_LIMIT",
    "STUDY_GUIDE_STRENGTH_LIMIT",
    "StudyGuideContentCallback",
    "generate_exam_study_guide",
]
