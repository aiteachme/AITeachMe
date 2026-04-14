"""Shared workflow authoring helpers with lazy exports.

Recommended public surface for new workflows:

- ``run_state_graph(...)``
- ``workflow_tracer(...).node(...)``
- ``@traceable_run(...)``
- ``tracked_step(...)``
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "InProcessEventBus",
    "WorkflowContext",
    "WorkflowError",
    "WorkflowGraphExport",
    "WorkflowEvent",
    "WorkflowResult",
    "run_state_graph",
    "invoke_state_graph",
    "traceable_run",
    "workflow_tracer",
    "WorkflowTraceBinding",
    "tracked_step",
    "emit_progress",
    "record_step_end",
    "record_step_start",
    "get_runtime_steps",
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
    "run_state_graph": "app.workflows.common.runtime",
    "invoke_state_graph": "app.workflows.common.runtime",
    "traceable_run": "app.workflows.common.observability",
    "workflow_tracer": "app.workflows.common.observability",
    "WorkflowTraceBinding": "app.workflows.common.observability",
    "tracked_step": "app.workflows.common.runtime_stats",
    "emit_progress": "app.workflows.common.runtime_stats",
    "record_step_end": "app.workflows.common.runtime_stats",
    "record_step_start": "app.workflows.common.runtime_stats",
    "get_runtime_steps": "app.workflows.common.runtime_stats",
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
