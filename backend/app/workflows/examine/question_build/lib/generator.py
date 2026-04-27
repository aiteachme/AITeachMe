"""LLM-backed exam question generation helpers.

This module owns the structured generation contract for high-quality exam
questions. It does not persist database rows; callers remain responsible for
mapping the generated drafts into QuestionTemplate / ExamPaperItem records.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.knowledge_unit import KnowledgeUnit
from app.shared.infra.exceptions import LLMTimeoutError
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.examine.question_build.prompts import (
    build_exam_question_requirement_messages,
    build_exam_knowledge_unit_filter_messages,
    build_exam_question_blueprint_messages,
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

_BLANK_TOKEN = "{{blank}}"
_TEXT_UNDERSCORE_PLACEHOLDER_RE = re.compile(r"\\text\{(_+)\}")
_CHOICE_LABEL_RE = re.compile(r"^\s*([A-Da-d])(?:[\.\)\]:：、\s]+)(.+)$")
_INLINE_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
_UNIT_REF_ID_RE = re.compile(r"\bknowledge_unit_id\s*[:=]\s*(\d+)\b", re.IGNORECASE)
_UNIT_REF_WEIGHT_RE = re.compile(
    r"\b(?:coverage_weight|weight)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\b",
    re.IGNORECASE,
)


def _escape_text_underscore_placeholders(value: str) -> str:
    """Keep blank placeholders valid inside KaTeX/LaTeX text blocks."""

    return _TEXT_UNDERSCORE_PLACEHOLDER_RE.sub(
        lambda match: r"\text{" + r"\_" * len(match.group(1)) + "}",
        value,
    )


def _clean_multiline_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_INLINE_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    cleaned_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if cleaned_lines and not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue
        cleaned_lines.append(line)
        previous_blank = False
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()
    return "\n".join(cleaned_lines).strip()


def _coerce_unit_ref_item(value: object) -> dict[str, object] | None:
    if isinstance(value, ExamQuestionUnitRef):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None

    cleaned = " ".join(value.replace("，", ",").split()).strip()
    if cleaned.casefold() in {"primary", "secondary"}:
        return None

    unit_match = _UNIT_REF_ID_RE.search(cleaned)
    if not unit_match:
        return None

    weight_match = _UNIT_REF_WEIGHT_RE.search(cleaned)
    try:
        weight = float(weight_match.group(1)) if weight_match else 1.0
    except (TypeError, ValueError):
        weight = 1.0
    return {
        "knowledge_unit_id": int(unit_match.group(1)),
        "coverage_weight": weight,
    }


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


class ExamKnowledgeUnitSelection(BaseModel):
    """Structured response from the candidate knowledge-unit filter step."""

    knowledge_unit_ids: list[int] = Field(default_factory=list)
    scope_include_terms: list[str] = Field(default_factory=list)
    scope_exclude_terms: list[str] = Field(default_factory=list)
    scope_strict: bool = False
    rationale: str = Field(default="", max_length=800)

    @model_validator(mode="before")
    @classmethod
    def _coerce_single_unit_id(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("knowledge_unit_ids"), int):
            return {**value, "knowledge_unit_ids": [value["knowledge_unit_ids"]]}
        return value

    @model_validator(mode="after")
    def _dedupe_unit_ids(self) -> "ExamKnowledgeUnitSelection":
        ids: list[int] = []
        seen: set[int] = set()
        for raw_id in self.knowledge_unit_ids:
            unit_id = int(raw_id or 0)
            if unit_id > 0 and unit_id not in seen:
                seen.add(unit_id)
                ids.append(unit_id)
        self.knowledge_unit_ids = ids
        self.scope_include_terms = _clean_short_terms(self.scope_include_terms)
        self.scope_exclude_terms = _clean_short_terms(self.scope_exclude_terms)
        self.rationale = " ".join(str(self.rationale or "").split()).strip()
        return self


class ExamQuestionGenerationSpec(BaseModel):
    """One requested question specification for the LLM generator."""

    item_order: int = Field(ge=1)
    knowledge_unit_id: int = Field(ge=1)
    knowledge_unit_ids: list[int] = Field(default_factory=list)
    question_type: QuestionTypeLiteral
    difficulty: DifficultyLiteral
    allocation_rationale: str = Field(default="", max_length=500)
    generation_prompt: str = Field(default="", max_length=1200)

    @model_validator(mode="before")
    @classmethod
    def _coerce_single_unit_id(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("knowledge_unit_ids"), int):
            return {**value, "knowledge_unit_ids": [value["knowledge_unit_ids"]]}
        return value

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
    generation_prompt: str = Field(default="", max_length=1200)

    @model_validator(mode="before")
    @classmethod
    def _coerce_single_unit_id(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("knowledge_unit_ids"), int):
            return {**value, "knowledge_unit_ids": [value["knowledge_unit_ids"]]}
        return value

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
            allocation_rationale=self.rationale,
            generation_prompt=self.generation_prompt,
        )


class ExamQuestionBlueprintBatch(BaseModel):
    """Structured blueprint response from the planning step."""

    blueprints: list[ExamQuestionBlueprint] = Field(default_factory=list, min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize_zero_based_item_orders(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        raw_blueprints = value.get("blueprints")
        if not isinstance(raw_blueprints, list):
            return value

        orders: list[int] = []
        for item in raw_blueprints:
            if not isinstance(item, dict):
                return value
            try:
                orders.append(int(item.get("item_order", 0)))
            except (TypeError, ValueError):
                return value

        expected_zero_based = set(range(len(raw_blueprints)))
        if set(orders) != expected_zero_based:
            return value

        normalized = dict(value)
        normalized["blueprints"] = [
            {**item, "item_order": int(item.get("item_order", 0)) + 1}
            for item in raw_blueprints
            if isinstance(item, dict)
        ]
        return normalized


class ExamQuestionRequirementPlan(BaseModel):
    """Per-question type and prompt constraints derived from the user's exam request."""

    item_order: int = Field(ge=1)
    question_type: QuestionTypeLiteral
    generation_prompt: str = Field(min_length=1, max_length=1200)

    @field_validator("generation_prompt")
    @classmethod
    def _clean_generation_prompt(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()


class ExamQuestionRequirementBatch(BaseModel):
    """Structured response for per-question generation prompts."""

    rationale: str = Field(default="", max_length=1000)
    prompts: list[ExamQuestionRequirementPlan] = Field(default_factory=list, min_length=1)

    @field_validator("rationale")
    @classmethod
    def _clean_rationale(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()

    @model_validator(mode="before")
    @classmethod
    def _normalize_zero_based_item_orders(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        raw_prompts = value.get("prompts")
        if not isinstance(raw_prompts, list):
            return value

        orders: list[int] = []
        for item in raw_prompts:
            if not isinstance(item, dict):
                return value
            try:
                orders.append(int(item.get("item_order", 0)))
            except (TypeError, ValueError):
                return value

        expected_zero_based = set(range(len(raw_prompts)))
        if set(orders) != expected_zero_based:
            return value

        normalized = dict(value)
        normalized["prompts"] = [
            {**item, "item_order": int(item.get("item_order", 0)) + 1}
            for item in raw_prompts
            if isinstance(item, dict)
        ]
        return normalized


class ExamQuestionDraft(BaseModel):
    """One validated exam question returned by the LLM workflow."""

    item_order: int = Field(ge=1)
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

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_unit_id(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        legacy_unit_id = int(value.get("knowledge_unit_id") or 0)
        if legacy_unit_id <= 0 or value.get("knowledge_unit_refs"):
            value.pop("knowledge_unit_id", None)
            return value
        migrated = dict(value)
        migrated.pop("knowledge_unit_id", None)
        migrated["knowledge_unit_refs"] = [
            {"knowledge_unit_id": legacy_unit_id, "coverage_weight": 1.0, "role": "primary"}
        ]
        return migrated

    @field_validator("stem", "explanation")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        cleaned = _clean_multiline_text(value)
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
            normalized_value = value.replace("，", ",").replace("、", ",").replace("；", ",")
            raw_items: list[object] = [
                item.strip()
                for item in normalized_value.split(",")
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

    @field_validator("knowledge_unit_refs", mode="before")
    @classmethod
    def _normalize_knowledge_unit_refs(cls, value: object) -> list[object]:
        if value is None or value == "":
            return []
        raw_items: list[object]
        if isinstance(value, dict) or isinstance(value, ExamQuestionUnitRef):
            raw_items = [value]
        elif isinstance(value, str):
            raw_items = [
                item.strip()
                for item in re.split(r"[;\n]+", value)
                if item.strip()
            ]
        elif isinstance(value, list):
            raw_items = value
        else:
            return []

        normalized: list[object] = []
        for item in raw_items:
            coerced = _coerce_unit_ref_item(item)
            if coerced is not None:
                normalized.append(coerced)
        return normalized

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
            if len(indices) < 1:
                raise ValueError("multiple_choice correct_indices must contain at least one index")
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


class ExamQuestionGenerationFailure(BaseModel):
    """One question-generation request that reached a terminal failed state."""

    item_order: int = Field(ge=1)
    question_type: QuestionTypeLiteral
    difficulty: DifficultyLiteral
    knowledge_unit_ids: list[int] = Field(default_factory=list)
    error_message: str = Field(default="", max_length=1200)


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
    normalized = (
        str(value or "")
        .replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace(";", ",")
    )
    return {
        token.strip().strip(".").strip(")").casefold()
        for token in normalized.split(",")
        if token.strip()
    }


def _normalize_true_false_answer(value: str) -> bool | None:
    normalized = " ".join(str(value or "").casefold().split()).strip()
    if normalized in {"true", "t", "yes", "y", "correct", "right", "1"}:
        return True
    if normalized in {"false", "f", "no", "n", "incorrect", "wrong", "0"}:
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


def _clean_short_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        if len(cleaned) < 2:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(cleaned[:80])
    return terms[:12]


def _unit_graph_node_payload(unit: KnowledgeUnit) -> dict[str, object]:
    return {
        "id": int(unit.id or 0),
        "name": str(unit.canonical_name or "").strip(),
    }


def _edge_graph_payload(edge: Mapping[str, object]) -> dict[str, object] | None:
    source_id = int(edge.get("source_id") or edge.get("source_node_id") or 0)
    target_id = int(edge.get("target_id") or edge.get("target_node_id") or 0)
    if source_id <= 0 or target_id <= 0:
        return None
    payload: dict[str, object] = {
        "source_id": source_id,
        "target_id": target_id,
    }
    edge_type = str(edge.get("edge_type") or edge.get("relation_type") or "").strip()
    if edge_type:
        payload["edge_type"] = edge_type
    description = " ".join(str(edge.get("description") or "").split()).strip()
    if description:
        payload["description"] = description[:240]
    for key in ("weight", "confidence"):
        raw_value = edge.get(key)
        if raw_value is None or raw_value == "":
            continue
        try:
            payload[key] = round(float(raw_value), 3)
        except (TypeError, ValueError):
            continue
    return payload


def _normalize_selection(
    selection: ExamKnowledgeUnitSelection,
    *,
    allowed_unit_ids: list[int],
    candidate_limit: int,
) -> ExamKnowledgeUnitSelection:
    allowed = set(allowed_unit_ids)
    ids: list[int] = []
    seen: set[int] = set()
    for raw_id in selection.knowledge_unit_ids:
        unit_id = int(raw_id or 0)
        if unit_id in allowed and unit_id not in seen:
            seen.add(unit_id)
            ids.append(unit_id)
    return ExamKnowledgeUnitSelection(
        knowledge_unit_ids=ids[: max(1, int(candidate_limit or 1))],
        scope_include_terms=selection.scope_include_terms,
        scope_exclude_terms=selection.scope_exclude_terms,
        scope_strict=selection.scope_strict,
        rationale=selection.rationale,
    )


def _spec_payload(spec: ExamQuestionGenerationSpec) -> dict[str, object]:
    return spec.model_dump(mode="json", exclude={"knowledge_unit_id", "generation_prompt"})


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
        draft_unit_ids = {ref.knowledge_unit_id for ref in item.knowledge_unit_refs}
        if draft_unit_ids and draft_unit_ids.isdisjoint(set(spec.knowledge_unit_ids)):
            raise ValueError(
                "llm question batch mismatch: "
                f"item_order={spec.item_order} knowledge_unit_refs={sorted(draft_unit_ids)} "
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
        item.knowledge_unit_refs = _normalize_weight_refs(
            item.knowledge_unit_refs,
            allowed_unit_ids=spec.knowledge_unit_ids,
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
            )
        )
    if not cleaned and allowed:
        cleaned.append(ExamQuestionUnitRef(knowledge_unit_id=allowed[0], coverage_weight=1.0))

    cleaned.sort(key=lambda item: item.coverage_weight, reverse=True)
    total = sum(item.coverage_weight for item in cleaned)
    if total <= 0:
        return [
            ExamQuestionUnitRef(
                knowledge_unit_id=item.knowledge_unit_id,
                coverage_weight=1.0 if index == 0 else 0.0,
            )
            for index, item in enumerate(cleaned)
        ]
    return [
        ExamQuestionUnitRef(
            knowledge_unit_id=item.knowledge_unit_id,
            coverage_weight=round(float(item.coverage_weight) / total, 4),
        )
        for index, item in enumerate(cleaned)
    ]


def _validate_blueprints(
    *,
    generated: list[ExamQuestionBlueprint],
    units: list[KnowledgeUnit],
    question_count: int,
    question_prompt_plans: list[ExamQuestionRequirementPlan] | None = None,
) -> list[ExamQuestionBlueprint]:
    unit_ids = {int(unit.id) for unit in units if unit.id is not None}
    by_order = {item.item_order: item for item in generated if item.item_order >= 1}
    prompt_plan_by_order = {
        item.item_order: item
        for item in list(question_prompt_plans or [])
        if item.item_order >= 1
    }
    normalized: list[ExamQuestionBlueprint] = []
    for order in range(1, max(1, question_count) + 1):
        item = by_order.get(order)
        if item is None:
            continue
        prompt_plan = prompt_plan_by_order.get(order)
        if prompt_plan is not None and item.question_type != prompt_plan.question_type:
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
                generation_prompt=prompt_plan.generation_prompt if prompt_plan is not None else item.generation_prompt,
            )
        )
    if len(normalized) == max(1, question_count):
        return normalized
    raise ValueError(
        "question blueprint planning returned invalid or incomplete items "
        f"(expected={max(1, question_count)}, usable={len(normalized)})"
    )


def _validate_generation_prompts(
    *,
    generated: list[ExamQuestionRequirementPlan],
    question_count: int,
) -> list[ExamQuestionRequirementPlan]:
    by_order = {item.item_order: item for item in generated if item.item_order >= 1}
    normalized: list[ExamQuestionRequirementPlan] = []
    for order in range(1, max(1, question_count) + 1):
        item = by_order.get(order)
        if item is None:
            continue
        normalized.append(
            ExamQuestionRequirementPlan(
                item_order=order,
                question_type=item.question_type,
                generation_prompt=item.generation_prompt,
            )
        )
    if len(normalized) == max(1, question_count):
        return normalized
    raise ValueError(
        "generation prompt planning returned invalid or incomplete items "
        f"(expected={max(1, question_count)}, usable={len(normalized)})"
    )


async def _select_exam_knowledge_units_once(
    *,
    subject: str,
    subject_name: str,
    subject_description: str,
    subject_user_intent: str,
    exam_mode: str,
    units: list[KnowledgeUnit],
    knowledge_graph_edges: list[dict[str, object]],
    question_count: int,
    candidate_limit: int,
    mastery_by_unit_id: dict[int, float] | None,
    priority_unit_ids: list[int],
    user_prompt: str,
    system_constraints: str,
    round_name: str,
) -> ExamKnowledgeUnitSelection:
    unit_ids = {int(unit.id) for unit in units if unit.id is not None}
    weak_unit_ids = [
        int(unit_id)
        for unit_id, mastery_score in (mastery_by_unit_id or {}).items()
        if int(unit_id or 0) in unit_ids and float(mastery_score) < 0.8
    ]
    graph_edges = [
        payload
        for edge in knowledge_graph_edges
        for payload in [_edge_graph_payload(edge)]
        if payload is not None
        and int(payload["source_id"]) in unit_ids
        and int(payload["target_id"]) in unit_ids
    ]
    messages = build_exam_knowledge_unit_filter_messages(
        subject_name=subject_name,
        subject_description=subject_description,
        subject_user_intent=subject_user_intent,
        exam_mode=exam_mode,
        requested_question_count=question_count,
        candidate_limit=candidate_limit,
        user_prompt=user_prompt,
        nodes=[_unit_graph_node_payload(unit) for unit in units],
        edges=graph_edges,
        priority_unit_ids=[unit_id for unit_id in priority_unit_ids if unit_id in unit_ids],
        weak_unit_ids=weak_unit_ids,
        system_constraints=system_constraints,
    )
    result = await acompletion_with_fallback(
        messages,
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        response_model=ExamKnowledgeUnitSelection,
        temperature=0.1,
        max_tokens=1400,
        extra_metadata={
            "substep": "exam.question_build.filter_units",
            "subject": subject,
            "exam_mode": exam_mode,
            "question_count": question_count,
            "candidate_limit": candidate_limit,
            "unit_count": len(units),
            "round": round_name,
        },
    )
    assert isinstance(result, ExamKnowledgeUnitSelection)
    return _normalize_selection(
        result,
        allowed_unit_ids=[int(unit.id) for unit in units if unit.id is not None],
        candidate_limit=candidate_limit,
    )


async def select_exam_knowledge_units(
    *,
    subject: str = "",
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
    exam_mode: str,
    units: list[KnowledgeUnit],
    question_count: int,
    candidate_limit: int,
    knowledge_graph_edges: list[dict[str, object]] | None = None,
    mastery_by_unit_id: dict[int, float] | None = None,
    priority_unit_ids: list[int] | None = None,
    user_prompt: str = "",
    system_constraints: str = "",
) -> ExamKnowledgeUnitSelection:
    """Use the LLM to select a compact candidate pool for blueprint planning."""

    eligible_units = [unit for unit in units if unit.id is not None]
    if not eligible_units:
        return ExamKnowledgeUnitSelection()

    normalized_count = max(1, int(question_count or 1))
    normalized_limit = min(
        len(eligible_units),
        max(1, int(candidate_limit or normalized_count or 1)),
    )
    priority_ids = [int(unit_id) for unit_id in list(priority_unit_ids or []) if int(unit_id or 0) > 0]

    selection = await _select_exam_knowledge_units_once(
        subject=subject,
        subject_name=subject_name,
        subject_description=subject_description,
        subject_user_intent=subject_user_intent,
        exam_mode=exam_mode,
        units=eligible_units,
        knowledge_graph_edges=list(knowledge_graph_edges or []),
        question_count=normalized_count,
        candidate_limit=normalized_limit,
        mastery_by_unit_id=mastery_by_unit_id,
        priority_unit_ids=priority_ids,
        user_prompt=user_prompt,
        system_constraints=system_constraints,
        round_name="graph",
    )
    if not selection.knowledge_unit_ids:
        raise ValueError("LLM knowledge-unit selection returned no usable ids")
    return selection


async def allocate_exam_question_knowledge_units(
    *,
    subject: str = "",
    subject_name: str = "",
    subject_description: str = "",
    subject_user_intent: str = "",
    exam_mode: str,
    units: list[KnowledgeUnit],
    question_count: int,
    mastery_by_unit_id: dict[int, float] | None = None,
    question_prompt_plans: list[ExamQuestionRequirementPlan] | None = None,
    user_prompt: str = "",
    system_constraints: str = "",
) -> list[ExamQuestionBlueprint]:
    """Plan question type and related knowledge units before item generation."""

    normalized_count = max(1, int(question_count or len(units) or 1))
    if not units:
        return []
    max_tokens = min(9000, max(2200, normalized_count * 360))
    messages = build_exam_question_blueprint_messages(
        subject_name=subject_name,
        subject_description=subject_description,
        subject_user_intent=subject_user_intent,
        exam_mode=exam_mode,
        requested_question_count=normalized_count,
        user_prompt=user_prompt,
        units=[_unit_payload_with_mastery(unit, mastery_by_unit_id) for unit in units],
        question_prompt_plans=[item.model_dump(mode="json") for item in list(question_prompt_plans or [])],
        system_constraints=system_constraints,
    )
    try:
        result = await acompletion_with_fallback(
            messages,
            call_purpose=LLMCallPurpose.CLASSIFY,
            model="light",
            response_model=ExamQuestionBlueprintBatch,
            temperature=0.45,
            max_tokens=max_tokens,
            extra_metadata={
                "substep": "exam.question_build.allocate_knowledge_units",
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
            question_prompt_plans=question_prompt_plans,
        )
    except (LLMTimeoutError, TimeoutError):
        raise
    except Exception as exc:
        raise RuntimeError(f"question blueprint planning failed: {exc}") from exc


async def plan_exam_question_requirements(
    *,
    exam_mode: str,
    question_count: int,
    user_prompt: str = "",
) -> tuple[list[ExamQuestionRequirementPlan], str]:
    """Plan per-question generation prompts from the user's global and item-specific constraints."""

    normalized_count = max(1, int(question_count or 1))
    max_tokens = min(6000, max(1200, normalized_count * 180))
    messages = build_exam_question_requirement_messages(
        exam_mode=exam_mode,
        requested_question_count=normalized_count,
        user_prompt=user_prompt,
    )
    try:
        result = await acompletion_with_fallback(
            messages,
            call_purpose=LLMCallPurpose.CLASSIFY,
            model="light",
            response_model=ExamQuestionRequirementBatch,
            temperature=0.2,
            max_tokens=max_tokens,
            extra_metadata={
                "substep": "exam.question_build.plan_question_requirements",
                "exam_mode": exam_mode,
                "question_count": normalized_count,
            },
        )
        assert isinstance(result, ExamQuestionRequirementBatch)
        prompts = _validate_generation_prompts(
            generated=result.prompts,
            question_count=normalized_count,
        )
        return prompts, result.rationale
    except (LLMTimeoutError, TimeoutError):
        raise
    except Exception as exc:
        raise RuntimeError(f"generation prompt planning failed: {exc}") from exc


async def _generate_one_exam_question(
    *,
    unit_by_id: dict[int, KnowledgeUnit],
    spec: ExamQuestionGenerationSpec,
    subject_profile: dict[str, str] | None = None,
    system_constraints: str = "",
) -> ExamQuestionDraft:
    batch_units = [unit_by_id[unit_id] for unit_id in spec.knowledge_unit_ids if unit_id in unit_by_id]
    messages = build_exam_question_messages(
        units=[_unit_payload(unit) for unit in batch_units],
        spec=_spec_payload(spec),
        generation_prompt=spec.generation_prompt,
        subject_profile=subject_profile,
        system_constraints=system_constraints,
    )
    last_error: Exception | None = None
    for attempt, max_tokens in enumerate((2600, 3600), start=1):
        try:
            result = await acompletion_with_fallback(
                messages,
                call_purpose=LLMCallPurpose.GENERATE,
                model="reason",
                response_model=ExamSingleQuestionResponse,
                temperature=0.65,
                max_tokens=max_tokens,
                extra_metadata={
                    "substep": "exam.question_build.generate_one",
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
    units: list[KnowledgeUnit],
    specs: list[ExamQuestionGenerationSpec],
    subject_profile: dict[str, str] | None = None,
    system_constraints: str = "",
    on_question_generated: Callable[[ExamQuestionDraft], Awaitable[None]] | None = None,
    on_question_failed: Callable[[ExamQuestionGenerationFailure], Awaitable[None]] | None = None,
    allow_partial: bool = False,
) -> list[ExamQuestionDraft]:
    """Generate exam questions for selected KnowledgeUnits via one LLM call per item."""

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

    async def generate_for_spec(
        spec: ExamQuestionGenerationSpec,
    ) -> tuple[ExamQuestionGenerationSpec, ExamQuestionDraft | Exception]:
        try:
            question = await _generate_one_exam_question(
                unit_by_id=unit_by_id,
                spec=spec,
                subject_profile=subject_profile,
                system_constraints=system_constraints,
            )
            return spec, question
        except Exception as exc:
            return spec, exc

    generated: list[ExamQuestionDraft] = []
    failed: list[ExamQuestionGenerationFailure] = []
    failures: list[str] = []
    failed_orders: list[int] = []
    tasks = [asyncio.create_task(generate_for_spec(spec)) for spec in specs]
    for completed_task in asyncio.as_completed(tasks):
        spec, result = await completed_task
        if isinstance(result, Exception):
            failed_orders.append(spec.item_order)
            failures.append(f"item_order={spec.item_order}: {result}")
            failure = ExamQuestionGenerationFailure(
                item_order=spec.item_order,
                question_type=spec.question_type,
                difficulty=spec.difficulty,
                knowledge_unit_ids=spec.knowledge_unit_ids,
                error_message=str(result),
            )
            failed.append(failure)
            if on_question_failed is not None:
                await on_question_failed(failure)
            continue
        generated.append(result)
        if on_question_generated is not None:
            await on_question_generated(result)

    if failures and not allow_partial:
        raise ValueError(
            "Exam question generation failed for "
            f"item_order values={failed_orders}; " + "; ".join(failures)
        )

    requested_orders = {spec.item_order for spec in specs}
    generated_orders = {item.item_order for item in generated}
    missing_orders = sorted(requested_orders - generated_orders)
    failed_order_set = {item.item_order for item in failed}
    unresolved_missing_orders = [order for order in missing_orders if order not in failed_order_set]
    if unresolved_missing_orders:
        raise ValueError(
            "LLM question generation returned an incomplete batch: "
            f"missing item_order values={unresolved_missing_orders}, unexpected item_order values=[]"
        )
    return sorted(generated, key=lambda item: item.item_order)


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
        model="reason",
        response_model=ExamQuestionBatch,
        temperature=0.65,
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
    "ExamKnowledgeUnitSelection",
    "ExamQuestionRequirementPlan",
    "ExamQuestionRequirementBatch",
    "ExamQuestionBatch",
    "ExamQuestionBlueprint",
    "ExamQuestionBlueprintBatch",
    "ExamQuestionDraft",
    "ExamQuestionGenerationFailure",
    "ExamQuestionGenerationSpec",
    "ExamSingleQuestionResponse",
    "ExamQuestionUnitRef",
    "generate_exam_from_text",
    "generate_exam_questions_for_units",
    "plan_exam_question_requirements",
    "allocate_exam_question_knowledge_units",
    "select_exam_knowledge_units",
]
