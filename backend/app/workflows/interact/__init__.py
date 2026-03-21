"""Interact workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "InteractWorkflowState",
    "WORKFLOW_EXPORTS",
    "build_chat_messages",
    "build_interact_workflow_graph",
    "format_sse_event",
    "retrieve",
    "stream_llm_events",
]

_ATTR_TO_MODULE = {
    "InteractWorkflowState": "app.workflows.interact.state",
    "WORKFLOW_EXPORTS": "app.workflows.interact.exports",
    "build_chat_messages": "app.workflows.interact.runtime",
    "build_interact_workflow_graph": "app.workflows.interact.graph",
    "format_sse_event": "app.workflows.interact.runtime",
    "retrieve": "app.workflows.interact.runtime",
    "stream_llm_events": "app.workflows.interact.runtime",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
