"""Examine workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ExamineWorkflowState",
    "WORKFLOW_EXPORTS",
    "build_examine_workflow_graph",
    "generate_exam",
    "generate_exam_from_text",
    "grade_exam",
]

_ATTR_TO_MODULE = {
    "ExamineWorkflowState": "app.workflows.examine.state",
    "WORKFLOW_EXPORTS": "app.workflows.examine.exports",
    "build_examine_workflow_graph": "app.workflows.examine.graph",
    "generate_exam": "app.workflows.examine.runtime",
    "generate_exam_from_text": "app.workflows.examine.runtime",
    "grade_exam": "app.workflows.examine.runtime",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
