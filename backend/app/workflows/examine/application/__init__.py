"""Examine API-facing application use cases.

Submodules:
  _helpers          – Shared DTOs, utilities, concurrency primitives
  question_build    – Question template build workflow trigger
  paper_generation  – Paper generation orchestrator
  grading           – Answer submission and grading logic
  queries           – Read queries (history, detail, question bank, delete)
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "ExamGenerationResult": "app.workflows.examine.application._helpers",
    "ExamGradingResult": "app.workflows.examine.application._helpers",
    "ExamPaperDetail": "app.workflows.examine.application._helpers",
    "QuestionBankItem": "app.workflows.examine.application._helpers",
    "QuestionBuildResult": "app.workflows.examine.application._helpers",
    "trigger_question_build": "app.workflows.examine.application.question_build",
    "trigger_exam_generate": "app.workflows.examine.application.paper_generation",
    "submit_exam_answers": "app.workflows.examine.application.grading",
    "trigger_exam_grade": "app.workflows.examine.application.grading",
    "get_exam_history": "app.workflows.examine.application.queries",
    "get_question_bank": "app.workflows.examine.application.queries",
    "delete_exam_paper": "app.workflows.examine.application.queries",
    "get_exam_paper_detail": "app.workflows.examine.application.queries",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value

__all__ = [
    # DTOs
    "ExamGenerationResult",
    "ExamGradingResult",
    "ExamPaperDetail",
    "QuestionBankItem",
    "QuestionBuildResult",
    # Commands
    "trigger_question_build",
    "trigger_exam_generate",
    "submit_exam_answers",
    "trigger_exam_grade",
    # Queries
    "get_exam_history",
    "get_question_bank",
    "delete_exam_paper",
    "get_exam_paper_detail",
]
