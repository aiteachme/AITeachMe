"""兼容性 shim — 实际实现已移至 app.teaching.checker。"""
from app.teaching.checker import (  # noqa: F401
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
