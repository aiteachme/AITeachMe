"""State contracts for the examine question-build workflow."""

from __future__ import annotations

from typing import TypedDict

from app.models.knowledge_unit import KnowledgeUnit


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
    knowledge_graph_edges: list[dict]
    mastery_by_unit_id: dict[int, float]
    priority_unit_ids: list[int]
    progress_callback: object | None


class QuestionBuildGraphOutput(TypedDict, total=False):
    candidate_unit_ids: list[int]
    candidate_unit_limit: int
    input_unit_count: int
    knowledge_graph_edge_count: int
    candidate_unit_count: int
    scope_include_terms: list[str]
    scope_exclude_terms: list[str]
    scope_strict: bool
    filter_strategy: str
    filter_rationale: str
    question_requirement_plans: list[dict]
    question_blueprints: list[dict]
    generated_questions: list[dict]
    generated_question_count: int
    failed_questions: list[dict]
    failed_question_count: int
    error: str
    workflow_elapsed_ms: int
    filter_ms: int
    requirements_plan_ms: int
    allocate_ms: int
    generate_ms: int


class QuestionBuildState(QuestionBuildGraphInput, QuestionBuildGraphOutput, total=False):
    pass


__all__ = [
    "QuestionBuildGraphInput",
    "QuestionBuildGraphOutput",
    "QuestionBuildState",
]
