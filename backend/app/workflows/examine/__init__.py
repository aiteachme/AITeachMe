"""Examine workflow stable exports.

This module restores a stable import surface for exam-generation workflows.
API-facing code should import the public helpers from here instead of reaching
into lane internals directly.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ExamQuestionDraft",
    "ExamQuestionGenerationSpec",
    "ExamQuestionBlueprint",
    "ExamQuestionUnitRef",
    "assign_question_knowledge_weights",
    "build_exam_grade_graph",
    "build_question_build_graph",
    "generate_exam_from_text",
    "generate_exam_questions_for_units",
    "plan_exam_question_blueprints",
    "run_exam_grade_workflow",
    "run_exam_study_guide_workflow",
    "run_question_build_workflow",
]

_ATTR_TO_MODULE = {
    "ExamQuestionDraft": "app.workflows.examine.question_build.lib.generator",
    "ExamQuestionGenerationSpec": "app.workflows.examine.question_build.lib.generator",
    "ExamQuestionBlueprint": "app.workflows.examine.question_build.lib.generator",
    "ExamQuestionUnitRef": "app.workflows.examine.question_build.lib.generator",
    "assign_question_knowledge_weights": "app.workflows.examine.question_build.lib.generator",
    "build_exam_grade_graph": "app.workflows.examine.exam_grade.graph",
    "build_question_build_graph": "app.workflows.examine.question_build.graph",
    "generate_exam_from_text": "app.workflows.examine.question_build.lib.generator",
    "generate_exam_questions_for_units": "app.workflows.examine.question_build.lib.generator",
    "plan_exam_question_blueprints": "app.workflows.examine.question_build.lib.generator",
    "run_exam_grade_workflow": "app.workflows.examine.exam_grade.graph",
    "run_exam_study_guide_workflow": "app.workflows.examine.exam_grade.graph",
    "run_question_build_workflow": "app.workflows.examine.question_build.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
