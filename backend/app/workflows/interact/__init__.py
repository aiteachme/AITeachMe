"""Interact workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "InteractWorkflowState",
    "WORKFLOW_EXPORTS",
    "build_chat_messages",
    "build_interact_workflow_graph",
    "create_interact_initial_state",
    "format_sse_event",
    "run_interact_workflow",
    "stream_chat_workflow",
]

_ATTR_TO_MODULE = {
    "InteractWorkflowState": "app.workflows.interact.chat.state",
    "WORKFLOW_EXPORTS": "app.workflows.interact.chat.graph",
    "build_chat_messages": "app.workflows.interact.chat.prompts",
    "build_interact_workflow_graph": "app.workflows.interact.chat.graph",
    "create_interact_initial_state": "app.workflows.interact.chat.graph",
    "format_sse_event": "app.workflows.interact.chat.lib",
    "run_interact_workflow": "app.workflows.interact.chat.graph",
    "stream_chat_workflow": "app.workflows.interact.chat.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
