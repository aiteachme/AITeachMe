"""Canonical question-build lane for the examine workflow module."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "QuestionBuildState",
    "QuestionBuildWorkflow",
    "build_question_build_graph",
    "run_question_build_workflow",
]

_ATTR_TO_MODULE = {
    "QuestionBuildState": "app.workflows.examine.question_build.graph",
    "QuestionBuildWorkflow": "app.workflows.examine.question_build.graph",
    "build_question_build_graph": "app.workflows.examine.question_build.graph",
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
