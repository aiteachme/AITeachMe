"""Examine workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ExamGradeState",
    "ExamineWorkflowState",
    "GeneratedExam",
    "GeneratedQuestion",
    "GradeResult",
    "GradeResultItem",
    "GradingResult",
    "GradingResultItem",
    "QuestionBuildState",
    "QuestionBuildWorkflow",
    "ExamGradeWorkflow",
    "WORKFLOW_EXPORTS",
    "assemble_paper",
    "build_exam_grade_graph",
    "build_examine_workflow_graph",
    "build_question_build_graph",
    "build_question_templates",
    "generate_exam",
    "generate_exam_from_text",
    "grade_exam",
    "grade_paper",
    "run_exam_grade_workflow",
    "run_question_build_workflow",
    "shuffle_single_choice_options",
]

_ATTR_TO_MODULE = {
    "ExamGradeState": "app.workflows.examine.state",
    "ExamineWorkflowState": "app.workflows.examine.state",
    "QuestionBuildState": "app.workflows.examine.state",
    "GeneratedExam": "app.workflows.examine.runtime",
    "GeneratedQuestion": "app.workflows.examine.runtime",
    "GradingResult": "app.workflows.examine.runtime",
    "GradingResultItem": "app.workflows.examine.runtime",
    "GradeResult": "app.workflows.examine.answer_grader",
    "GradeResultItem": "app.workflows.examine.answer_grader",
    "QuestionBuildWorkflow": "app.workflows.examine.question_build_workflow",
    "ExamGradeWorkflow": "app.workflows.examine.exam_grade_workflow",
    "WORKFLOW_EXPORTS": "app.workflows.examine.exports",
    "assemble_paper": "app.workflows.examine.paper_assembler",
    "build_exam_grade_graph": "app.workflows.examine.graph",
    "build_examine_workflow_graph": "app.workflows.examine.graph",
    "build_question_build_graph": "app.workflows.examine.graph",
    "build_question_templates": "app.workflows.examine.question_builder",
    "generate_exam": "app.workflows.examine.runtime",
    "generate_exam_from_text": "app.workflows.examine.runtime",
    "grade_exam": "app.workflows.examine.runtime",
    "grade_paper": "app.workflows.examine.answer_grader",
    "run_exam_grade_workflow": "app.workflows.examine.exam_grade_workflow",
    "run_question_build_workflow": "app.workflows.examine.question_build_workflow",
    "shuffle_single_choice_options": "app.workflows.examine.paper_assembler",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
