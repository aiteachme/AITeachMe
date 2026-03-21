"""Profile workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ProfileWorkflowState",
    "WORKFLOW_EXPORTS",
    "build_profile_workflow_graph",
    "generate_report_suggestions",
]

_ATTR_TO_MODULE = {
    "ProfileWorkflowState": "app.workflows.profile.state",
    "WORKFLOW_EXPORTS": "app.workflows.profile.exports",
    "build_profile_workflow_graph": "app.workflows.profile.graph",
    "generate_report_suggestions": "app.workflows.profile.runtime",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
