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
    "InProcessEventBus": "app.shared.infra.workflow.events",
    "WorkflowContext": "app.shared.infra.workflow.context",
    "WorkflowError": "app.shared.infra.workflow.result",
    "WorkflowGraphExport": "app.shared.infra.workflow.graph_export",
    "WorkflowEvent": "app.shared.infra.workflow.events",
    "WorkflowResult": "app.shared.infra.workflow.result",
    "run_state_graph": "app.shared.infra.workflow.runtime",
    "invoke_state_graph": "app.shared.infra.workflow.runtime",
    "traceable_run": "app.shared.infra.workflow.observability",
    "workflow_tracer": "app.shared.infra.workflow.observability",
    "WorkflowTraceBinding": "app.shared.infra.workflow.observability",
    "tracked_step": "app.shared.infra.workflow.runtime_stats",
    "emit_progress": "app.shared.infra.workflow.runtime_stats",
    "record_step_end": "app.shared.infra.workflow.runtime_stats",
    "record_step_start": "app.shared.infra.workflow.runtime_stats",
    "get_runtime_steps": "app.shared.infra.workflow.runtime_stats",
    "err_result": "app.shared.infra.workflow.result",
    "ok_result": "app.shared.infra.workflow.result",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
