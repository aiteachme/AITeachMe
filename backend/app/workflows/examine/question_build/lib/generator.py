"""LLM-backed exam question generation helpers.

This module owns the structured generation contract for high-quality exam
questions. It does not persist database rows; callers remain responsible for
mapping the generated drafts into QuestionTemplate / ExamPaperItem records.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.knowledge_unit import KnowledgeUnit
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.examine.question_build.prompts import (
    build_exam_question_messages,
    build_text_exam_messages,
)

QuestionTypeLiteral = Literal[
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
]
DifficultyLiteral = Literal["easy", "medium", "hard"]
T = TypeVar("T")

_MAX_BATCH_SIZE = 6


class ExamQuestionGenerationSpec(BaseModel):
    """One requested question specification for the LLM generator."""

    item_order: int = Field(ge=1)
    knowledge_unit_id: int = Field(ge=1)
    question_type: QuestionTypeLiteral
    difficulty: DifficultyLiteral


class ExamQuestionDraft(BaseModel):
    """One validated exam question returned by the LLM workflow."""

    item_order: int = Field(ge=1)
    knowledge_unit_id: int = Field(ge=0)
    question_type: QuestionTypeLiteral
    difficulty: DifficultyLiteral
    stem: str = Field(min_length=8, max_length=1000)
    options: list[str] | None = None
    correct_answer: str = Field(min_length=1, max_length=500)
    explanation: str = Field(min_length=8, max_length=2000)

    @field_validator("stem", "correct_answer", "explanation")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            raise ValueError("text field cannot be empty")
        return cleaned

    @field_validator("options")
    @classmethod
    def _normalize_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [" ".join(str(item or "").split()).strip() for item in value]
        cleaned = [item for item in cleaned if item]
        return cleaned or None

    @model_validator(mode="after")
    def _validate_shape(self) -> "ExamQuestionDraft":
        if self.question_type == "single_choice":
            options = self.options or []
            if len(options) != 4:
                raise ValueError("single_choice questions must contain exactly 4 options")
            if len({item.casefold() for item in options}) != 4:
                raise ValueError("single_choice options must be distinct")
            if self.correct_answer not in options:
                raise ValueError("single_choice correct_answer must equal one option exactly")
            return self

        if self.question_type == "multiple_choice":
            options = self.options or []
            if len(options) != 4:
                raise ValueError("multiple_choice questions must contain exactly 4 options")
            if len({item.casefold() for item in options}) != 4:
                raise ValueError("multiple_choice options must be distinct")
            selected = _split_multi_choice_answer(self.correct_answer)
            option_keys = {_choice_key(option) for option in options}
            if len(selected) < 2:
                raise ValueError("multiple_choice correct_answer must contain at least 2 choices")
            if not selected <= option_keys:
                raise ValueError("multiple_choice correct_answer must use option labels from options")
            return self

        if self.question_type == "true_false":
            options = self.options or []
            if options and {item.casefold() for item in options} != {"true", "false"}:
                raise ValueError("true_false options must be omitted or exactly ['True', 'False']")
            if _normalize_true_false_answer(self.correct_answer) is None:
                raise ValueError("true_false correct_answer must be True or False")
            return self

        if self.options:
            raise ValueError("non-choice questions must not provide options")

        if self.question_type == "fill_blank" and len(self.correct_answer) > 80:
            raise ValueError("fill_blank correct_answer must stay concise")

        return self


def _choice_key(value: str) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return ""
    head = cleaned[0].casefold()
    if head in {"a", "b", "c", "d"}:
        return head
    return cleaned.casefold()


def _split_multi_choice_answer(value: str) -> set[str]:
    normalized = str(value or "").replace("，", ",").replace("、", ",").replace("；", ",")
    return {
        token.strip().strip(".").strip(")").casefold()
        for token in normalized.split(",")
        if token.strip()
    }


def _normalize_true_false_answer(value: str) -> bool | None:
    normalized = " ".join(str(value or "").casefold().split()).strip()
    if normalized in {"true", "t", "yes", "y", "正确", "对", "是"}:
        return True
    if normalized in {"false", "f", "no", "n", "错误", "错", "否"}:
        return False
    return None


class ExamQuestionBatch(BaseModel):
    """Structured batch response for one LLM question-generation call."""

    questions: list[ExamQuestionDraft] = Field(default_factory=list)


def _unit_payload(unit: KnowledgeUnit) -> dict[str, object]:
    return {
        "knowledge_unit_id": int(unit.id or 0),
        "name": str(unit.canonical_name or "").strip(),
        "knowledge_unit_type": str(unit.knowledge_unit_type or "").strip(),
        "summary": " ".join(str(unit.summary or "").split()).strip(),
    }


def _spec_payload(spec: ExamQuestionGenerationSpec) -> dict[str, object]:
    return spec.model_dump(mode="json")


def _batched(items: Sequence[T], *, batch_size: int) -> list[list[T]]:
    return [
        list(items[index : index + batch_size])
        for index in range(0, len(items), batch_size)
    ]


def _validate_batch_alignment(
    *,
    generated: list[ExamQuestionDraft],
    requested_specs: list[ExamQuestionGenerationSpec],
) -> list[ExamQuestionDraft]:
    spec_by_order = {spec.item_order: spec for spec in requested_specs}
    generated_by_order = {item.item_order: item for item in generated}

    missing_orders = sorted(set(spec_by_order) - set(generated_by_order))
    extra_orders = sorted(set(generated_by_order) - set(spec_by_order))
    if missing_orders or extra_orders:
        raise ValueError(
            f"llm question batch mismatch: missing_orders={missing_orders}, extra_orders={extra_orders}"
        )

    normalized: list[ExamQuestionDraft] = []
    for spec in requested_specs:
        item = generated_by_order[spec.item_order]
        if item.knowledge_unit_id != spec.knowledge_unit_id:
            raise ValueError(
                "llm question batch mismatch: "
                f"item_order={spec.item_order} knowledge_unit_id={item.knowledge_unit_id} "
                f"expected={spec.knowledge_unit_id}"
            )
        if item.question_type != spec.question_type:
            raise ValueError(
                "llm question batch mismatch: "
                f"item_order={spec.item_order} question_type={item.question_type} "
                f"expected={spec.question_type}"
            )
        if item.difficulty != spec.difficulty:
            raise ValueError(
                "llm question batch mismatch: "
                f"item_order={spec.item_order} difficulty={item.difficulty} "
                f"expected={spec.difficulty}"
            )
        normalized.append(item)
    return normalized


async def generate_exam_questions_for_units(
    *,
    subject: str,
    exam_mode: str,
    units: list[KnowledgeUnit],
    specs: list[ExamQuestionGenerationSpec],
    focus_prompt: str = "",
    user_prompt: str = "",
    style_prompt: str = "",
) -> list[ExamQuestionDraft]:
    """Generate exam questions for a selected set of KnowledgeUnits via LLM."""

    unit_by_id = {
        int(unit.id): unit
        for unit in units
        if unit.id is not None
    }
    missing_units = sorted(
        spec.knowledge_unit_id
        for spec in specs
        if spec.knowledge_unit_id not in unit_by_id
    )
    if missing_units:
        raise ValueError(f"missing KnowledgeUnits for specs: {missing_units}")

    generated_questions: list[ExamQuestionDraft] = []
    for spec_batch in _batched(specs, batch_size=_MAX_BATCH_SIZE):
        batch_unit_ids = {spec.knowledge_unit_id for spec in spec_batch}
        batch_units = [unit_by_id[unit_id] for unit_id in batch_unit_ids]
        messages = build_exam_question_messages(
            subject=subject,
            exam_mode=exam_mode,
            focus_prompt=focus_prompt,
            user_prompt=user_prompt,
            style_prompt=style_prompt,
            requested_question_count=len(spec_batch),
            units=[_unit_payload(unit) for unit in batch_units],
            specs=[_spec_payload(spec) for spec in spec_batch],
        )
        result = await acompletion_with_fallback(
            messages,
            call_purpose=LLMCallPurpose.GENERATE,
            model="primary",
            response_model=ExamQuestionBatch,
            temperature=0.35,
            max_tokens=2400,
            extra_metadata={
                "substep": "exam.question_build",
                "subject": subject,
                "exam_mode": exam_mode,
                "batch_size": len(spec_batch),
            },
        )
        assert isinstance(result, ExamQuestionBatch)
        generated_questions.extend(
            _validate_batch_alignment(
                generated=result.questions,
                requested_specs=spec_batch,
            )
        )

    generated_questions.sort(key=lambda item: item.item_order)
    return generated_questions


async def generate_exam_from_text(
    *,
    subject: str,
    knowledge_text: str,
    num_questions: int = 5,
    difficulty: DifficultyLiteral = "medium",
) -> list[ExamQuestionDraft]:
    """Compatibility helper for the playground script."""

    normalized_count = max(1, min(int(num_questions), 12))
    messages = build_text_exam_messages(
        subject=subject,
        knowledge_text=knowledge_text,
        num_questions=normalized_count,
        difficulty=difficulty,
    )
    result = await acompletion_with_fallback(
        messages,
        call_purpose=LLMCallPurpose.GENERATE,
        model="primary",
        response_model=ExamQuestionBatch,
        temperature=0.35,
        max_tokens=2800,
        extra_metadata={
            "substep": "exam.question_build.playground",
            "subject": subject,
            "question_count": normalized_count,
        },
    )
    assert isinstance(result, ExamQuestionBatch)
    return result.questions


__all__ = [
    "ExamQuestionBatch",
    "ExamQuestionDraft",
    "ExamQuestionGenerationSpec",
    "generate_exam_from_text",
    "generate_exam_questions_for_units",
]
