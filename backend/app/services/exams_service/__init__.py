"""Exam service package — modularized from the monolithic exams_service.py.

Submodules:
  _helpers          – Shared DTOs, utilities, concurrency primitives
  question_build    – Question template build workflow trigger
  paper_generation  – Paper generation orchestrator
  grading           – Answer submission and grading logic
  queries           – Read queries (history, detail, question bank, delete)
"""

from ._helpers import (
    ExamGenerationResult,
    ExamGradingResult,
    ExamPaperDetail,
    QuestionBankItem,
    QuestionBuildResult,
)
from .grading import submit_exam_answers, trigger_exam_grade
from .paper_generation import trigger_exam_generate
from .queries import delete_exam_paper, get_exam_history, get_exam_paper_detail, get_question_bank
from .question_build import trigger_question_build

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
