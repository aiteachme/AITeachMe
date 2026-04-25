"""LLM-backed exam question generation helpers.

This module owns the structured generation contract for high-quality exam
questions. It does not persist database rows; callers remain responsible for
mapping the generated drafts into QuestionTemplate / ExamPaperItem records.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.knowledge_unit import KnowledgeUnit
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.examine.question_build.prompts import (
    build_exam_question_blueprint_messages,
    build_exam_question_messages,
    build_question_weight_messages,
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
_BLANK_TOKEN = "{{blank}}"
_TEXT_UNDERSCORE_PLACEHOLDER_RE = re.compile(r"\\text\{(_+)\}")
_CHOICE_LABEL_RE = re.compile(r"^\s*([A-Da-d])(?:[\.\)\]．、:：]\s*)(.+)$")


def _escape_text_underscore_placeholders(value: str) -> str:
    """Keep blank placeholders valid inside KaTeX/LaTeX text blocks."""

    return _TEXT_UNDERSCORE_PLACEHOLDER_RE.sub(
        lambda match: r"\text{" + r"\_" * len(match.group(1)) + "}",
        value,
    )


def _contains_blank_token_inside_latex(value: str) -> bool:
    in_math = False
    delimiter = ""
    index = 0
    while index < len(value):
        if in_math and value.startswith(_BLANK_TOKEN, index):
            return True
        if value[index] == "$" and (index == 0 or value[index - 1] != "\\"):
            current_delimiter = "$$" if value.startswith("$$", index) else "$"
            if in_math and delimiter == current_delimiter:
                in_math = False
                delimiter = ""
            elif not in_math:
                in_math = True
                delimiter = current_delimiter
            index += len(current_delimiter)
            continue
        index += 1
    return False


class ExamQuestionUnitRef(BaseModel):
    """Weighted knowledge-unit coverage for one generated question."""

    knowledge_unit_id: int = Field(ge=1)
    coverage_weight: float = Field(ge=0.0, le=1.0)
    role: Literal["primary", "secondary"] = "secondary"


class ExamQuestionGenerationSpec(BaseModel):
    """One requested question specification for the LLM generator."""

    item_order: int = Field(ge=1)
    knowledge_unit_id: int = Field(ge=1)
    knowledge_unit_ids: list[int] = Field(default_factory=list)
    question_type: QuestionTypeLiteral
    difficulty: DifficultyLiteral

    @model_validator(mode="after")
    def _ensure_unit_ids(self) -> "ExamQuestionGenerationSpec":
        ids: list[int] = []
        seen: set[int] = set()
        for raw_id in [self.knowledge_unit_id, *self.knowledge_unit_ids]:
            unit_id = int(raw_id or 0)
            if unit_id > 0 and unit_id not in seen:
                seen.add(unit_id)
                ids.append(unit_id)
        if not ids:
            raise ValueError("spec must include at least one knowledge_unit_id")
        self.knowledge_unit_ids = ids[:4]
        self.knowledge_unit_id = self.knowledge_unit_ids[0]
        return self


class ExamQuestionBlueprint(BaseModel):
    """Question plan decided before concrete item generation."""

    item_order: int = Field(ge=1)
    knowledge_unit_ids: list[int] = Field(default_factory=list, min_length=1)
    question_type: QuestionTypeLiteral
    difficulty: DifficultyLiteral
    rationale: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _dedupe_unit_ids(self) -> "ExamQuestionBlueprint":
        ids: list[int] = []
        seen: set[int] = set()
        for raw_id in self.knowledge_unit_ids:
            unit_id = int(raw_id or 0)
            if unit_id > 0 and unit_id not in seen:
                seen.add(unit_id)
                ids.append(unit_id)
        if not ids:
            raise ValueError("blueprint must include at least one knowledge_unit_id")
        self.knowledge_unit_ids = ids[:4]
        return self

    def to_generation_spec(self) -> ExamQuestionGenerationSpec:
        return ExamQuestionGenerationSpec(
            item_order=self.item_order,
            knowledge_unit_id=self.knowledge_unit_ids[0],
            knowledge_unit_ids=self.knowledge_unit_ids,
            question_type=self.question_type,
            difficulty=self.difficulty,
        )


class ExamQuestionBlueprintBatch(BaseModel):
    """Structured blueprint response from the planning step."""

    blueprints: list[ExamQuestionBlueprint] = Field(default_factory=list, min_length=1)


class ExamQuestionDraft(BaseModel):
    """One validated exam question returned by the LLM workflow."""

    item_order: int = Field(ge=1)
    knowledge_unit_id: int = Field(ge=0)
    question_type: QuestionTypeLiteral
    difficulty: DifficultyLiteral
    stem: str = Field(min_length=8, max_length=1000)
    options: list[str] | None = Field(
        default=None,
        description=(
            "Canonical choice format only: for single_choice and multiple_choice, "
            "return exactly four plain option-text strings in order. Do not prefix "
            "options with A/B/C/D labels; the application renders labels by index. "
            "For all other question types, omit options."
        ),
    )
    correct_answer: str = Field(
        default="",
        min_length=1,
        max_length=500,
        description=(
            "Derived answer text. For single_choice and multiple_choice, prefer correct_indices "
            "and omit this field; the backend converts indices to A/B/C/D labels. "
            "For true_false use True or False; fill_blank and short_answer use concise answer text."
        ),
    )
    correct_indices: list[int] | None = Field(
        default=None,
        description=(
            "Canonical choice-answer format only: for single_choice, return one zero-based index "
            "such as [0]; for multiple_choice, return all correct zero-based indices such as [0, 2]. "
            "Omit this field for non-choice questions."
        ),
    )
    explanation: str = Field(min_length=8, max_length=2000)
    knowledge_unit_refs: list[ExamQuestionUnitRef] = Field(default_factory=list)

    @field_validator("stem", "explanation")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            raise ValueError("text field cannot be empty")
        return _escape_text_underscore_placeholders(cleaned)

    @field_validator("correct_answer", mode="before")
    @classmethod
    def _strip_answer_text(cls, value: object) -> str:
        if isinstance(value, bool):
            return "True" if value else "False"
        cleaned = " ".join(str(value or "").split()).strip()
        return _escape_text_underscore_placeholders(cleaned) if cleaned else ""

    @field_validator("correct_indices", mode="before")
    @classmethod
    def _normalize_correct_indices(cls, value: object) -> list[int] | None:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            raw_items: list[object] = [
                item.strip()
                for item in value.replace("，", ",").replace("、", ",").split(",")
                if item.strip()
            ]
        elif isinstance(value, list):
            raw_items = value
        else:
            raise ValueError("correct_indices must be a list of zero-based integers")

        indices: list[int] = []
        for item in raw_items:
            if isinstance(item, str) and item.strip().casefold() in {"a", "b", "c", "d"}:
                index = ord(item.strip().casefold()) - ord("a")
            else:
                index = int(item)
            if index not in indices:
                indices.append(index)
        return indices or None

    @field_validator("options", mode="before")
    @classmethod
    def _normalize_options(cls, value: object) -> list[str] | None:
        if value is None:
            return None

        if isinstance(value, dict):
            ordered_items = sorted(
                value.items(),
                key=lambda item: "abcd".find(str(item[0]).strip().casefold()[:1])
                if str(item[0]).strip().casefold()[:1] in "abcd"
                else 99,
            )
            raw_items = [
                str(option or "").strip()
                for key, option in ordered_items
            ]
        elif isinstance(value, list):
            raw_items = [
                str(item.get("text", item.get("value", ""))).strip()
                if isinstance(item, dict)
                else str(item or "")
                for item in value
            ]
        else:
            raise ValueError("options must be a list or label-to-option mapping")

        cleaned = [" ".join(str(item or "").split()).strip() for item in raw_items]
        cleaned = [_choice_body(item) for item in cleaned]
        cleaned = [_escape_text_underscore_placeholders(item) for item in cleaned if item]
        return cleaned or None

    @model_validator(mode="after")
    def _validate_shape(self) -> "ExamQuestionDraft":
        text_fields = [self.stem, self.explanation]
        if self.correct_answer:
            text_fields.append(self.correct_answer)
        text_fields.extend(self.options or [])
        if any(_contains_blank_token_inside_latex(value) for value in text_fields):
            raise ValueError("{{blank}} placeholders must stay outside LaTeX math")

        if self.question_type == "single_choice":
            options = self.options or []
            if len(options) != 4:
                raise ValueError("single_choice questions must contain exactly 4 options")
            if len({item.casefold() for item in options}) != 4:
                raise ValueError("single_choice options must be distinct")
            indices = self.correct_indices or _choice_indices_from_answer(self.correct_answer, options)
            if len(indices) != 1:
                raise ValueError("single_choice correct_indices must contain exactly one index")
            if any(index < 0 or index >= len(options) for index in indices):
                raise ValueError("single_choice correct_indices must be in range 0..3")
            self.correct_indices = indices
            self.correct_answer = _choice_label(indices[0])
            return self

        if self.question_type == "multiple_choice":
            options = self.options or []
            if len(options) != 4:
                raise ValueError("multiple_choice questions must contain exactly 4 options")
            if len({item.casefold() for item in options}) != 4:
                raise ValueError("multiple_choice options must be distinct")
            indices = self.correct_indices or _choice_indices_from_answer(self.correct_answer, options)
            if len(indices) < 2:
                raise ValueError("multiple_choice correct_indices must contain at least 2 indices")
            if any(index < 0 or index >= len(options) for index in indices):
                raise ValueError("multiple_choice correct_indices must be in range 0..3")
            self.correct_indices = sorted(indices)
            self.correct_answer = ",".join(_choice_label(index) for index in self.correct_indices)
            return self

        if self.question_type == "true_false":
            if self.correct_indices:
                raise ValueError("non-choice questions must not provide correct_indices")
            options = self.options or []
            if options and {item.casefold() for item in options} != {"true", "false"}:
                raise ValueError("true_false options must be omitted or exactly ['True', 'False']")
            if _normalize_true_false_answer(self.correct_answer) is None:
                raise ValueError("true_false correct_answer must be True or False")
            return self

        if self.correct_indices:
            raise ValueError("non-choice questions must not provide correct_indices")

        if self.options:
            raise ValueError("non-choice questions must not provide options")

        if not self.correct_answer:
            raise ValueError("correct_answer cannot be empty")

        if self.question_type == "fill_blank" and len(self.correct_answer) > 80:
            raise ValueError("fill_blank correct_answer must stay concise")

        return self


class ExamQuestionBatch(BaseModel):
    """Structured batch response for one LLM question-generation call."""

    questions: list[ExamQuestionDraft] = Field(default_factory=list, min_length=1)


class ExamSingleQuestionResponse(BaseModel):
    """Structured response for one parallel question-generation call."""

    question: ExamQuestionDraft

    @model_validator(mode="before")
    @classmethod
    def _accept_direct_question_payload(cls, value: object) -> object:
        if isinstance(value, dict) and "question" not in value and "item_order" in value:
            return {"question": value}
        return value


class ExamQuestionWeightResult(BaseModel):
    """Structured LLM response for one question's knowledge-unit weights."""

    item_order: int = Field(ge=1)
    knowledge_unit_refs: list[ExamQuestionUnitRef] = Field(default_factory=list, min_length=1)


def _choice_label(index: int) -> str:
    return chr(ord("A") + index)


def _choice_answer_key(value: str) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return ""
    if cleaned.casefold() in {"a", "b", "c", "d"}:
        return cleaned.casefold()
    label_match = _CHOICE_LABEL_RE.match(cleaned)
    if label_match and label_match.group(2):
        return label_match.group(1).casefold()
    return cleaned.casefold()


def _choice_body(value: str) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    label_match = _CHOICE_LABEL_RE.match(cleaned)
    if label_match and label_match.group(2):
        return str(label_match.group(2) or "").strip()
    return cleaned


def _choice_indices_from_answer(value: str, options: list[str]) -> list[int]:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return []

    indices: list[int] = []
    for token in _split_multi_choice_answer(cleaned):
        if token in {"a", "b", "c", "d"}:
            index = ord(token) - ord("a")
            if index < len(options) and index not in indices:
                indices.append(index)
        elif len(token) == 1 and token.isalpha() and 99 not in indices:
            indices.append(99)

    if indices:
        return sorted(indices)

    answer_body = _choice_body(cleaned).casefold()
    for index, option in enumerate(options):
        if _choice_body(option).casefold() == answer_body:
            return [index]
    return []


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


def _unit_payload(unit: KnowledgeUnit) -> dict[str, object]:
    return {
        "knowledge_unit_id": int(unit.id or 0),
        "name": str(unit.canonical_name or "").strip(),
        "knowledge_unit_type": str(unit.knowledge_unit_type or "").strip(),
        "summary": " ".join(str(unit.summary or "").split()).strip(),
    }


def _unit_payload_with_mastery(
    unit: KnowledgeUnit,
    mastery_by_unit_id: dict[int, float] | None = None,
) -> dict[str, object]:
    payload = _unit_payload(unit)
    unit_id = int(unit.id or 0)
    if mastery_by_unit_id and unit_id in mastery_by_unit_id:
        payload["mastery_score"] = round(float(mastery_by_unit_id[unit_id]), 3)
    return payload


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
            "LLM question generation returned an incomplete batch: "
            f"missing item_order values={missing_orders}, unexpected item_order values={extra_orders}"
        )

    normalized: list[ExamQuestionDraft] = []
    for spec in requested_specs:
        item = generated_by_order[spec.item_order]
        if item.knowledge_unit_id not in set(spec.knowledge_unit_ids):
            raise ValueError(
                "llm question batch mismatch: "
                f"item_order={spec.item_order} knowledge_unit_id={item.knowledge_unit_id} "
                f"expected_one_of={spec.knowledge_unit_ids}"
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


def _normalize_weight_refs(
    refs: list[ExamQuestionUnitRef],
    *,
    allowed_unit_ids: list[int],
) -> list[ExamQuestionUnitRef]:
    allowed = [int(unit_id) for unit_id in allowed_unit_ids if int(unit_id or 0) > 0]
    allowed_set = set(allowed)
    cleaned: list[ExamQuestionUnitRef] = []
    seen: set[int] = set()
    for ref in refs:
        unit_id = int(ref.knowledge_unit_id)
        if unit_id not in allowed_set or unit_id in seen:
            continue
        seen.add(unit_id)
        cleaned.append(
            ExamQuestionUnitRef(
                knowledge_unit_id=unit_id,
                coverage_weight=max(0.0, min(float(ref.coverage_weight), 1.0)),
                role="primary" if not cleaned else "secondary",
            )
        )
    if not cleaned and allowed:
        cleaned.append(ExamQuestionUnitRef(knowledge_unit_id=allowed[0], coverage_weight=1.0, role="primary"))

    total = sum(item.coverage_weight for item in cleaned)
    if total <= 0:
        return [
            ExamQuestionUnitRef(
                knowledge_unit_id=item.knowledge_unit_id,
                coverage_weight=1.0 if index == 0 else 0.0,
                role="primary" if index == 0 else "secondary",
            )
            for index, item in enumerate(cleaned)
        ]
    return [
        ExamQuestionUnitRef(
            knowledge_unit_id=item.knowledge_unit_id,
            coverage_weight=round(float(item.coverage_weight) / total, 4),
            role="primary" if index == 0 else "secondary",
        )
        for index, item in enumerate(cleaned)
    ]


def _fallback_blueprints(
    *,
    units: list[KnowledgeUnit],
    question_count: int,
    requested_difficulty: DifficultyLiteral | str,
    exam_mode: str,
) -> list[ExamQuestionBlueprint]:
    eligible_units = [unit for unit in units if unit.id is not None]
    if not eligible_units:
        return []
    normalized_count = max(1, int(question_count or len(eligible_units)))
    difficulty = str(requested_difficulty or "medium").strip().lower()
    difficulty_cycle = (
        ["easy", "medium", "hard"]
        if difficulty == "mixed"
        else [difficulty if difficulty in {"easy", "medium", "hard"} else "medium"]
    )
    type_cycle: list[QuestionTypeLiteral] = (
        ["single_choice", "fill_blank", "short_answer"]
        if exam_mode == "paper_exam"
        else ["single_choice", "fill_blank"]
    )
    blueprints: list[ExamQuestionBlueprint] = []
    for index in range(normalized_count):
        primary = eligible_units[index % len(eligible_units)]
        related: list[int] = [int(primary.id or 0)]
        if len(eligible_units) > 1:
            secondary = eligible_units[(index + 1) % len(eligible_units)]
            if secondary.id is not None and secondary.id != primary.id:
                related.append(int(secondary.id))
        blueprints.append(
            ExamQuestionBlueprint(
                item_order=index + 1,
                knowledge_unit_ids=related[:2],
                question_type=type_cycle[index % len(type_cycle)],
                difficulty=difficulty_cycle[index % len(difficulty_cycle)],  # type: ignore[arg-type]
                rationale="Fallback blueprint based on ordered knowledge units.",
            )
        )
    return blueprints


def _validate_blueprints(
    *,
    generated: list[ExamQuestionBlueprint],
    units: list[KnowledgeUnit],
    question_count: int,
    requested_difficulty: str,
    exam_mode: str,
) -> list[ExamQuestionBlueprint]:
    unit_ids = {int(unit.id) for unit in units if unit.id is not None}
    by_order = {item.item_order: item for item in generated if item.item_order >= 1}
    normalized: list[ExamQuestionBlueprint] = []
    for order in range(1, max(1, question_count) + 1):
        item = by_order.get(order)
        if item is None:
            continue
        ids = [unit_id for unit_id in item.knowledge_unit_ids if unit_id in unit_ids]
        if not ids:
            continue
        normalized.append(
            ExamQuestionBlueprint(
                item_order=order,
                knowledge_unit_ids=ids,
                question_type=item.question_type,
                difficulty=item.difficulty,
                rationale=item.rationale,
            )
        )
    if len(normalized) == max(1, question_count):
        return normalized
    return _fallback_blueprints(
        units=units,
        question_count=question_count,
        requested_difficulty=requested_difficulty,
        exam_mode=exam_mode,
    )


async def plan_exam_question_blueprints(
    *,
    subject: str,
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
    subject_context: str = "",
    exam_mode: str,
    units: list[KnowledgeUnit],
    question_count: int,
    requested_difficulty: str = "medium",
    mastery_by_unit_id: dict[int, float] | None = None,
    focus_prompt: str = "",
    user_prompt: str = "",
    style_prompt: str = "",
) -> list[ExamQuestionBlueprint]:
    """Plan question type and related knowledge units before item generation."""

    normalized_count = max(1, int(question_count or len(units) or 1))
    if not units:
        return []
    messages = build_exam_question_blueprint_messages(
        subject=subject,
        subject_name=subject_name,
        subject_description=subject_description,
        subject_user_intent=subject_user_intent,
        exam_mode=exam_mode,
        subject_context=subject_context,
        requested_question_count=normalized_count,
        requested_difficulty=requested_difficulty,
        focus_prompt=focus_prompt,
        user_prompt=user_prompt,
        style_prompt=style_prompt,
        units=[_unit_payload_with_mastery(unit, mastery_by_unit_id) for unit in units],
    )
    try:
        result = await acompletion_with_fallback(
            messages,
            call_purpose=LLMCallPurpose.CLASSIFY,
            model="light",
            response_model=ExamQuestionBlueprintBatch,
            temperature=0.2,
            max_tokens=2200,
            extra_metadata={
                "substep": "exam.question_build.plan_blueprints",
                "subject": subject,
                "exam_mode": exam_mode,
                "question_count": normalized_count,
                "unit_count": len(units),
            },
        )
        assert isinstance(result, ExamQuestionBlueprintBatch)
        return _validate_blueprints(
            generated=result.blueprints,
            units=units,
            question_count=normalized_count,
            requested_difficulty=requested_difficulty,
            exam_mode=exam_mode,
        )
    except Exception:
        return _fallback_blueprints(
            units=units,
            question_count=normalized_count,
            requested_difficulty=requested_difficulty,
            exam_mode=exam_mode,
        )


async def _generate_one_exam_question(
    *,
    subject: str,
    subject_name: str,
    subject_description: str,
    subject_user_intent: str,
    exam_mode: str,
    subject_context: str,
    unit_by_id: dict[int, KnowledgeUnit],
    spec: ExamQuestionGenerationSpec,
    focus_prompt: str,
    user_prompt: str,
    style_prompt: str,
) -> ExamQuestionDraft:
    batch_units = [unit_by_id[unit_id] for unit_id in spec.knowledge_unit_ids if unit_id in unit_by_id]
    messages = build_exam_question_messages(
        subject=subject,
        subject_name=subject_name,
        subject_description=subject_description,
        subject_user_intent=subject_user_intent,
        exam_mode=exam_mode,
        subject_context=subject_context,
        focus_prompt=focus_prompt,
        user_prompt=user_prompt,
        style_prompt=style_prompt,
        requested_question_count=1,
        units=[_unit_payload(unit) for unit in batch_units],
        specs=[_spec_payload(spec)],
    )
    last_error: Exception | None = None
    for attempt, max_tokens in enumerate((2600, 3600), start=1):
        try:
            result = await acompletion_with_fallback(
                messages,
                call_purpose=LLMCallPurpose.GENERATE,
                model="primary",
                response_model=ExamSingleQuestionResponse,
                temperature=0.35,
                max_tokens=max_tokens,
                extra_metadata={
                    "substep": "exam.question_build.generate_one",
                    "subject": subject,
                    "exam_mode": exam_mode,
                    "item_order": spec.item_order,
                    "unit_count": len(batch_units),
                    "attempt": attempt,
                },
            )
            assert isinstance(result, ExamSingleQuestionResponse)
            return _validate_batch_alignment(generated=[result.question], requested_specs=[spec])[0]
        except Exception as exc:
            last_error = exc
    raise ValueError(
        "LLM question generation failed for "
        f"item_order={spec.item_order}: {last_error}"
    ) from last_error


async def generate_exam_questions_for_units(
    *,
    subject: str,
    exam_mode: str,
    units: list[KnowledgeUnit],
    specs: list[ExamQuestionGenerationSpec],
    subject_context: str = "",
    focus_prompt: str = "",
    user_prompt: str = "",
    style_prompt: str = "",
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
) -> list[ExamQuestionDraft]:
    """Generate exam questions for a selected set of KnowledgeUnits via LLM.

    Compatibility helper: callers may still pass explicit specs. Internally this
    now supports multi-unit specs and parallel per-question generation.
    """

    unit_by_id = {
        int(unit.id): unit
        for unit in units
        if unit.id is not None
    }
    missing_units = sorted(
        unit_id
        for spec in specs
        for unit_id in spec.knowledge_unit_ids
        if unit_id not in unit_by_id
    )
    if missing_units:
        raise ValueError(f"missing KnowledgeUnits for specs: {missing_units}")

    if len(specs) <= _MAX_BATCH_SIZE and all(len(spec.knowledge_unit_ids) == 1 for spec in specs):
        generated_questions: list[ExamQuestionDraft] = []
        batch_call_failed = False
        for spec_batch in _batched(specs, batch_size=_MAX_BATCH_SIZE):
            batch_unit_ids = {spec.knowledge_unit_id for spec in spec_batch}
            batch_units = [unit_by_id[unit_id] for unit_id in batch_unit_ids]
            messages = build_exam_question_messages(
                subject=subject,
                subject_name=subject_name,
                subject_description=subject_description,
                subject_user_intent=subject_user_intent,
                exam_mode=exam_mode,
                subject_context=subject_context,
                focus_prompt=focus_prompt,
                user_prompt=user_prompt,
                style_prompt=style_prompt,
                requested_question_count=len(spec_batch),
                units=[_unit_payload(unit) for unit in batch_units],
                specs=[_spec_payload(spec) for spec in spec_batch],
            )
            try:
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
            except Exception:
                generated_questions = []
                batch_call_failed = True
                break
            assert isinstance(result, ExamQuestionBatch)
            generated_questions.extend(
                _validate_batch_alignment(
                    generated=result.questions,
                    requested_specs=spec_batch,
                )
            )
        if not batch_call_failed:
            generated_questions.sort(key=lambda item: item.item_order)
            return generated_questions

    generated_results = await asyncio.gather(
        *(
            _generate_one_exam_question(
                subject=subject,
                subject_name=subject_name,
                subject_description=subject_description,
                subject_user_intent=subject_user_intent,
                exam_mode=exam_mode,
                subject_context=subject_context,
                unit_by_id=unit_by_id,
                spec=spec,
                focus_prompt=focus_prompt,
                user_prompt=user_prompt,
                style_prompt=style_prompt,
            )
            for spec in specs
        ),
        return_exceptions=True,
    )

    generated: list[ExamQuestionDraft] = []
    failures: list[str] = []
    failed_orders: list[int] = []
    for spec, result in zip(specs, generated_results, strict=True):
        if isinstance(result, Exception):
            failed_orders.append(spec.item_order)
            failures.append(f"item_order={spec.item_order}: {result}")
            continue
        generated.append(result)

    if failures:
        raise ValueError(
            "Exam question generation failed for "
            f"item_order values={failed_orders}; " + "; ".join(failures)
        )

    requested_orders = {spec.item_order for spec in specs}
    generated_orders = {item.item_order for item in generated}
    missing_orders = sorted(requested_orders - generated_orders)
    if missing_orders:
        raise ValueError(
            "LLM question generation returned an incomplete batch: "
            f"missing item_order values={missing_orders}, unexpected item_order values=[]"
        )
    return sorted(generated, key=lambda item: item.item_order)


async def assign_question_knowledge_weights(
    *,
    subject: str,
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
    units: list[KnowledgeUnit],
    blueprints: list[ExamQuestionBlueprint],
    questions: list[ExamQuestionDraft],
) -> list[ExamQuestionDraft]:
    """Assign per-question coverage weights to related knowledge units in parallel."""

    unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
    blueprint_by_order = {item.item_order: item for item in blueprints}

    async def assign_one(question: ExamQuestionDraft) -> ExamQuestionDraft:
        blueprint = blueprint_by_order.get(question.item_order)
        allowed_ids = list(blueprint.knowledge_unit_ids if blueprint is not None else [question.knowledge_unit_id])
        allowed_units = [unit_by_id[unit_id] for unit_id in allowed_ids if unit_id in unit_by_id]
        fallback_refs = _normalize_weight_refs(
            [
                ExamQuestionUnitRef(
                    knowledge_unit_id=unit_id,
                    coverage_weight=1.0 if index == 0 else 0.35,
                    role="primary" if index == 0 else "secondary",
                )
                for index, unit_id in enumerate(allowed_ids)
            ],
            allowed_unit_ids=allowed_ids,
        )
        try:
            result = await acompletion_with_fallback(
                build_question_weight_messages(
                    subject=subject,
                    subject_name=subject_name,
                    subject_description=subject_description,
                    subject_user_intent=subject_user_intent,
                    question=question.model_dump(mode="json", exclude={"knowledge_unit_refs"}),
                    units=[_unit_payload(unit) for unit in allowed_units],
                ),
                call_purpose=LLMCallPurpose.CLASSIFY,
                model="light",
                response_model=ExamQuestionWeightResult,
                temperature=0.0,
                max_tokens=700,
                extra_metadata={
                    "substep": "exam.question_build.weight_units",
                    "subject": subject,
                    "item_order": question.item_order,
                },
            )
            assert isinstance(result, ExamQuestionWeightResult)
            refs = _normalize_weight_refs(result.knowledge_unit_refs, allowed_unit_ids=allowed_ids)
        except Exception:
            refs = fallback_refs
        question.knowledge_unit_refs = refs
        question.knowledge_unit_id = refs[0].knowledge_unit_id if refs else question.knowledge_unit_id
        return question

    weighted = await asyncio.gather(*(assign_one(question) for question in questions))
    return sorted(weighted, key=lambda item: item.item_order)


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
    "ExamQuestionBlueprint",
    "ExamQuestionBlueprintBatch",
    "ExamQuestionDraft",
    "ExamQuestionGenerationSpec",
    "ExamSingleQuestionResponse",
    "ExamQuestionUnitRef",
    "ExamQuestionWeightResult",
    "assign_question_knowledge_weights",
    "generate_exam_from_text",
    "generate_exam_questions_for_units",
    "plan_exam_question_blueprints",
]
