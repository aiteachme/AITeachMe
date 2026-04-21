"""State contracts for the examine question-build workflow."""

from __future__ import annotations

from typing import TypedDict

from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.examine.question_build.lib.generator import ExamQuestionGenerationSpec


class QuestionBuildGraphInput(TypedDict, total=False):
    subject: str
    exam_mode: str
    focus_prompt: str
    user_prompt: str
    style_prompt: str
    units: list[KnowledgeUnit]
    specs: list[ExamQuestionGenerationSpec]
    progress_callback: object | None


class QuestionBuildGraphOutput(TypedDict, total=False):
    generated_questions: list[dict]
    error: str
    workflow_elapsed_ms: int


class QuestionBuildState(QuestionBuildGraphInput, QuestionBuildGraphOutput, total=False):
    pass


__all__ = [
    "QuestionBuildGraphInput",
    "QuestionBuildGraphOutput",
    "QuestionBuildState",
]
