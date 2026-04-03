"""State types for the examine workflow package."""

from __future__ import annotations

from typing import Any, TypedDict

from app.workflows.examine.answer_grader import GradeResult
from app.workflows.profile.mastery_updater import MasteryUpdateResult


class ExamineWorkflowState(TypedDict, total=False):
    question_templates_ready: bool
    exam_paper_ready: bool
    exam_graded: bool
    mastery_updated: bool
    review_scheduled: bool


class QuestionBuildState(TypedDict, total=False):
    subject: str
    user_id: str
    unit_ids: list[int]
    questions_per_unit: int
    job_id: int
    exam_mode: str
    preferred_question_types: list[str]
    user_prompt: str | None
    focus_prompt: str | None
    style_profile: Any
    curriculum_version_id: int | None
    template_context_signature: str | None
    context_locked: bool
    scope_locked: bool
    focus_teaching_unit_ids: list[int]
    focus_node_ids: list[int]
    templates_created: int
    warnings: list[str]
    error: str | None
    created_template_ids: list[int]


class ExamGradeState(TypedDict, total=False):
    exam_paper_id: int
    job_id: int
    grade_result: GradeResult | None
    mastery_result: MasteryUpdateResult | None
    review_tasks: list[int]
    error: str | None
