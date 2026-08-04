"""Canonical runtime contract for built-in exam question types."""

from __future__ import annotations

from typing import Literal, cast

QuestionTypeLiteral = Literal[
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
]
QuestionTypeGradingKind = Literal["objective", "subjective"]

CANONICAL_QUESTION_TYPE_KEYS: tuple[QuestionTypeLiteral, ...] = (
    "single_choice",
    "multiple_choice",
    "true_false",
    "fill_blank",
    "short_answer",
)
SUPPORTED_QUESTION_TYPE_KEYS = frozenset(CANONICAL_QUESTION_TYPE_KEYS)
LEGACY_QUESTION_TYPE_ALIASES = {"multi_choice": "multiple_choice"}
OBJECTIVE_QUESTION_TYPE_KEYS = frozenset({"single_choice", "multiple_choice", "true_false"})
SUBJECTIVE_QUESTION_TYPE_KEYS = frozenset({"fill_blank", "short_answer"})


class UnsupportedQuestionTypeError(ValueError):
    """Raised when a question type has no published runtime implementation."""

    def __init__(self, question_type: object) -> None:
        self.question_type = str(question_type or "").strip().lower()
        display_value = self.question_type or "<empty>"
        super().__init__(f"Unsupported question type: {display_value}")


def normalize_question_type_key(value: object) -> str:
    """Normalize a key and map supported historical aliases to canonical keys."""

    normalized = str(value or "").strip().lower()
    return LEGACY_QUESTION_TYPE_ALIASES.get(normalized, normalized)


def require_supported_question_type_key(value: object) -> QuestionTypeLiteral:
    """Return a canonical key or fail closed for an unsupported type."""

    normalized = normalize_question_type_key(value)
    if normalized not in SUPPORTED_QUESTION_TYPE_KEYS:
        raise UnsupportedQuestionTypeError(value)
    return cast(QuestionTypeLiteral, normalized)


def is_supported_question_type(value: object) -> bool:
    return normalize_question_type_key(value) in SUPPORTED_QUESTION_TYPE_KEYS


def question_type_grading_kind(value: object) -> QuestionTypeGradingKind:
    normalized = require_supported_question_type_key(value)
    if normalized in OBJECTIVE_QUESTION_TYPE_KEYS:
        return "objective"
    if normalized in SUBJECTIVE_QUESTION_TYPE_KEYS:
        return "subjective"
    raise UnsupportedQuestionTypeError(value)  # pragma: no cover - exhaustive guard


__all__ = [
    "CANONICAL_QUESTION_TYPE_KEYS",
    "LEGACY_QUESTION_TYPE_ALIASES",
    "OBJECTIVE_QUESTION_TYPE_KEYS",
    "QuestionTypeGradingKind",
    "QuestionTypeLiteral",
    "SUBJECTIVE_QUESTION_TYPE_KEYS",
    "SUPPORTED_QUESTION_TYPE_KEYS",
    "UnsupportedQuestionTypeError",
    "is_supported_question_type",
    "normalize_question_type_key",
    "question_type_grading_kind",
    "require_supported_question_type_key",
]
