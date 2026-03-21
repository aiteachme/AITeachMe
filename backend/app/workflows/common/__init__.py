"""Shared workflow helpers with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "InProcessEventBus",
    "WorkflowContext",
    "WorkflowError",
    "WorkflowGraphExport",
    "WorkflowEvent",
    "WorkflowResult",
    "err_result",
    "ok_result",
]

_ATTR_TO_MODULE = {
    "InProcessEventBus": "app.workflows.common.events",
    "WorkflowContext": "app.workflows.common.context",
    "WorkflowError": "app.workflows.common.result",
    "WorkflowGraphExport": "app.workflows.common.graph_export",
    "WorkflowEvent": "app.workflows.common.events",
    "WorkflowResult": "app.workflows.common.result",
    "err_result": "app.workflows.common.result",
    "ok_result": "app.workflows.common.result",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
