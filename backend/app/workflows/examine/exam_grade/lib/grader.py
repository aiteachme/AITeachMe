"""LLM-backed grading workflow for exam paper items."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import ExamPaperItem
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support import get_llm_concurrency_limit
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.observability.trace import traceable_with_context
from app.shared.infra.runtime import gather_with_concurrency
from app.workflows.examine.exam_grade.prompts import (
    build_objective_feedback_messages,
    build_subjective_grade_messages,
)

_MULTI_CHOICE_SPLIT_RE = re.compile(r"[\s,，;；/、|]+")
_OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "multi_choice", "true_false"}
_SUBJECTIVE_TYPES = {"fill_blank", "short_answer"}


class ObjectiveFeedbackPayload(BaseModel):
    feedback_text: str = Field(min_length=8, max_length=1200)
    error_cause_label: str | None = Field(default=None, max_length=80)

    @field_validator("feedback_text")
    @classmethod
    def _strip_feedback_text(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()


class SubjectiveGradePayload(BaseModel):
    is_correct: bool
    score_obtained: float = Field(ge=0.0, le=1.0)
    feedback_text: str = Field(min_length=8, max_length=1600)
    error_cause_label: str | None = Field(default=None, max_length=80)

    @field_validator("feedback_text")
    @classmethod
    def _strip_feedback_text(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()


@dataclass(frozen=True)
class ExamItemGradeDecision:
    is_correct: bool
    score_obtained: float
    score_max: float
    feedback_text: str
    error_cause_label: str | None
    grading_mode: Literal["objective_rule", "subjective_llm", "subjective_fallback"]


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split()).strip()


def _split_multi_choice_tokens(value: str | None) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    return {
        token
        for token in _MULTI_CHOICE_SPLIT_RE.split(normalized)
        if token
    }


def _normalize_true_false_token(value: str | None) -> str:
    normalized = _normalize_text(value)
    if normalized in {"true", "t", "yes", "y", "正确", "对", "是"}:
        return "true"
    if normalized in {"false", "f", "no", "n", "错误", "错", "否"}:
        return "false"
    return normalized


def _is_objective_type(question_type: str) -> bool:
    return (question_type or "").strip().lower() in _OBJECTIVE_TYPES


def _build_default_feedback(*, item: ExamPaperItem, is_correct: bool, subjective: bool = False) -> str:
    user_answer = (item.answer_content or "").strip()
    if not user_answer:
        return (
            f"你本题未作答。参考答案是：{item.answer_snapshot}。"
            f"建议先回顾这道题考查的关键点，再结合解析重新整理思路。"
        )
    if is_correct:
        return (
            "本题判定正确。你的作答与标准答案在关键结论上保持一致，"
            "可以继续关注表达的清晰度与步骤的完整性。"
        )
    if subjective:
        return (
            f"本题未判为完全正确。参考答案是：{item.answer_snapshot}。"
            "你的作答与标准结论或关键推理之间仍有差距，建议对照解析补齐核心步骤。"
        )
    return (
        f"本题判定错误。参考答案是：{item.answer_snapshot}。"
        "建议回看题干条件与对应知识点，确认自己为何会选择当前答案。"
    )


def _grade_objective_correctness(item: ExamPaperItem) -> bool:
    question_type = (item.question_type or "").strip().lower()
    expected = _normalize_text(item.answer_snapshot)
    answer = _normalize_text(item.answer_content)
    if not expected or not answer:
        return False
    if question_type in {"multiple_choice", "multi_choice"}:
        return _split_multi_choice_tokens(expected) == _split_multi_choice_tokens(answer)
    if question_type == "true_false":
        return _normalize_true_false_token(expected) == _normalize_true_false_token(answer)
    return answer == expected


@traceable_with_context(
    name="考试：客观题反馈",
    run_type="chain",
    metadata_factory=lambda course_name, item, is_correct: {
        "substep": "exam.grade.objective_feedback",
        "question_type": item.question_type,
        "item_order": item.item_order,
        "question_template_id": item.question_template_id,
        "is_correct": bool(is_correct),
    },
    tags_factory=lambda course_name, item, is_correct: [
        "exam-grade",
        "objective",
        f"question-type:{str(item.question_type or '').strip().lower() or 'unknown'}",
        f"judgement:{'correct' if is_correct else 'incorrect'}",
    ],
)
async def _generate_objective_feedback(course_name: str, item: ExamPaperItem, *, is_correct: bool) -> tuple[str, str | None]:
    try:
        result = await acompletion_with_fallback(
            build_objective_feedback_messages(
                course_name=course_name,
                question_type=item.question_type,
                stem=item.stem_snapshot,
                options=_parse_options(item.options_snapshot_json),
                correct_answer=item.answer_snapshot,
                reference_explanation=item.explanation_snapshot,
                user_answer=item.answer_content,
                is_correct=is_correct,
            ),
            call_purpose=LLMCallPurpose.GRADE,
            model="reason",
            response_model=ObjectiveFeedbackPayload,
            temperature=0.1,
            max_tokens=500,
            extra_metadata={
                "substep": "exam.grade.objective_feedback",
                "question_type": item.question_type,
            },
        )
        assert isinstance(result, ObjectiveFeedbackPayload)
        return result.feedback_text, result.error_cause_label
    except Exception:
        return (
            _build_default_feedback(item=item, is_correct=is_correct, subjective=False),
            None if is_correct else "knowledge_gap",
        )


@traceable_with_context(
    name="考试：主观题判分",
    run_type="chain",
    metadata_factory=lambda course_name, item: {
        "substep": "exam.grade.subjective_item",
        "question_type": item.question_type,
        "item_order": item.item_order,
        "question_template_id": item.question_template_id,
    },
    tags_factory=lambda course_name, item: [
        "exam-grade",
        "subjective",
        f"question-type:{str(item.question_type or '').strip().lower() or 'unknown'}",
    ],
)
async def _grade_subjective_item(course_name: str, item: ExamPaperItem) -> ExamItemGradeDecision:
    user_answer = _normalize_text(item.answer_content)
    if not user_answer:
        return ExamItemGradeDecision(
            is_correct=False,
            score_obtained=0.0,
            score_max=float(item.score or 1.0),
            feedback_text=_build_default_feedback(item=item, is_correct=False, subjective=True),
            error_cause_label="knowledge_gap",
            grading_mode="subjective_fallback",
        )

    try:
        result = await acompletion_with_fallback(
            build_subjective_grade_messages(
                course_name=course_name,
                question_type=item.question_type,
                stem=item.stem_snapshot,
                correct_answer=item.answer_snapshot,
                reference_explanation=item.explanation_snapshot,
                user_answer=item.answer_content,
            ),
            call_purpose=LLMCallPurpose.GRADE,
            model="reason",
            response_model=SubjectiveGradePayload,
            temperature=0.1,
            max_tokens=700,
            extra_metadata={
                "substep": "exam.grade.subjective_judge",
                "question_type": item.question_type,
            },
        )
        assert isinstance(result, SubjectiveGradePayload)
        bounded_score = max(0.0, min(float(item.score or 1.0), float(item.score or 1.0) * result.score_obtained))
        return ExamItemGradeDecision(
            is_correct=bool(result.is_correct),
            score_obtained=bounded_score,
            score_max=float(item.score or 1.0),
            feedback_text=result.feedback_text,
            error_cause_label=None if result.is_correct else (result.error_cause_label or "knowledge_gap"),
            grading_mode="subjective_llm",
        )
    except Exception:
        expected = _normalize_text(item.answer_snapshot)
        fallback_correct = bool(expected and (user_answer == expected))
        return ExamItemGradeDecision(
            is_correct=fallback_correct,
            score_obtained=float(item.score or 1.0) if fallback_correct else 0.0,
            score_max=float(item.score or 1.0),
            feedback_text=_build_default_feedback(item=item, is_correct=fallback_correct, subjective=True),
            error_cause_label=None if fallback_correct else "unknown",
            grading_mode="subjective_fallback",
        )


def _parse_options(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    normalized = [str(item).strip() for item in payload if str(item).strip()]
    return normalized or None


@traceable_with_context(
    name="考试：整卷判题",
    run_type="chain",
    metadata_factory=lambda *, course_name, items: {
        "substep": "exam.grade.paper",
        "course_name": course_name,
        "item_count": len(items),
    },
    tags_factory=lambda *, course_name, items: [
        "exam-grade",
        "paper-grading",
    ],
)
async def grade_exam_items_with_workflow(
    *,
    course_name: str,
    items: list[ExamPaperItem],
) -> list[ExamItemGradeDecision]:
    async def _grade_item(item: ExamPaperItem) -> ExamItemGradeDecision:
        if _is_objective_type(item.question_type):
            is_correct = _grade_objective_correctness(item)
            feedback_text, error_cause_label = await _generate_objective_feedback(
                course_name,
                item,
                is_correct=is_correct,
            )
            return ExamItemGradeDecision(
                is_correct=is_correct,
                score_obtained=float(item.score or 1.0) if is_correct else 0.0,
                score_max=float(item.score or 1.0),
                feedback_text=feedback_text,
                error_cause_label=None if is_correct else (error_cause_label or "knowledge_gap"),
                grading_mode="objective_rule",
            )

        if (item.question_type or "").strip().lower() in _SUBJECTIVE_TYPES:
            return await _grade_subjective_item(course_name, item)

        # Unknown question types degrade to subjective handling.
        return await _grade_subjective_item(course_name, item)

    return await gather_with_concurrency(
        items,
        _grade_item,
        limit=min(8, get_llm_concurrency_limit()),
    )


__all__ = [
    "ExamItemGradeDecision",
    "ObjectiveFeedbackPayload",
    "SubjectiveGradePayload",
    "grade_exam_items_with_workflow",
]
