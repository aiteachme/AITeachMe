"""Shared workflow helpers with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "InProcessEventBus",
    "TERMINAL_NODE",
    "WorkflowContext",
    "WorkflowConditionalEdgeSpec",
    "WorkflowDiagramSpec",
    "WorkflowEdgeSpec",
    "WorkflowError",
    "WorkflowEvent",
    "WorkflowResult",
    "build_state_graph_from_topology",
    "err_result",
    "ok_result",
    "render_mermaid_flowchart",
]

_ATTR_TO_MODULE = {
    "InProcessEventBus": "app.workflows.common.events",
    "TERMINAL_NODE": "app.workflows.common.topology",
    "WorkflowContext": "app.workflows.common.context",
    "WorkflowConditionalEdgeSpec": "app.workflows.common.topology",
    "WorkflowDiagramSpec": "app.workflows.common.topology",
    "WorkflowEdgeSpec": "app.workflows.common.topology",
    "WorkflowError": "app.workflows.common.result",
    "WorkflowEvent": "app.workflows.common.events",
    "WorkflowResult": "app.workflows.common.result",
    "build_state_graph_from_topology": "app.workflows.common.state_graph_builder",
    "err_result": "app.workflows.common.result",
    "ok_result": "app.workflows.common.result",
    "render_mermaid_flowchart": "app.workflows.common.topology",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
