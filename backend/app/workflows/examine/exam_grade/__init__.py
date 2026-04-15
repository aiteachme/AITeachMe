"""Canonical exam-grade lane for the examine workflow module."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ExamGradeState",
    "ExamGradeWorkflow",
    "build_exam_grade_graph",
    "run_exam_grade_workflow",
]

_ATTR_TO_MODULE = {
    "ExamGradeState": "app.workflows.examine.exam_grade.graph",
    "ExamGradeWorkflow": "app.workflows.examine.exam_grade.graph",
    "build_exam_grade_graph": "app.workflows.examine.exam_grade.graph",
    "run_exam_grade_workflow": "app.workflows.examine.exam_grade.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
