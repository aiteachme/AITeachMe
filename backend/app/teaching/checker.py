"""Compatibility facade for the canonical checker implementation."""

from app.shared.infra.checker import (
    CheckResult,
    CommonMistake,
    Rubric,
    RubricCriterion,
    check_answer,
    check_exact,
    check_keywords,
    check_with_llm,
    load_rubric,
)

__all__ = [
    "CheckResult",
    "CommonMistake",
    "Rubric",
    "RubricCriterion",
    "check_answer",
    "check_exact",
    "check_keywords",
    "check_with_llm",
    "load_rubric",
]
