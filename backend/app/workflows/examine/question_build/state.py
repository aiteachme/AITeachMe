"""State contracts for the examine question-build workflow."""

from __future__ import annotations

from typing import TypedDict

from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.examine.question_build.lib.generator import ExamQuestionGenerationSpec


class QuestionBuildGraphInput(TypedDict, total=False):
    subject: str
    subject_name: str
    subject_description: str
    subject_user_intent: str
    exam_mode: str
    subject_context: str
    user_prompt: str
    system_constraints: str
    question_count: int
    units: list[KnowledgeUnit]
    mastery_by_unit_id: dict[int, float]
    specs: list[ExamQuestionGenerationSpec]
    progress_callback: object | None


class QuestionBuildGraphOutput(TypedDict, total=False):
    question_blueprints: list[dict]
    generated_questions: list[dict]
    error: str
    workflow_elapsed_ms: int
    plan_ms: int
    generate_ms: int
    weight_ms: int


class QuestionBuildState(QuestionBuildGraphInput, QuestionBuildGraphOutput, total=False):
    pass


__all__ = [
    "QuestionBuildGraphInput",
    "QuestionBuildGraphOutput",
    "QuestionBuildState",
]
