"""Compatibility re-exports for legacy digest application imports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "DigestBuildRequestedEvent",
    "DigestGraphCompletedEvent",
    "DigestGraphFailedEvent",
    "DocGenCompletedEvent",
    "DocGenFailedEvent",
    "DocGenRequestedEvent",
    "WORKFLOW_EXPORTS",
    "create_docgen_initial_state",
    "create_graph_digest_initial_state",
    "run_docgen_workflow",
    "run_graph_digest_workflow",
]

_ATTR_TO_MODULE = {
    "DigestBuildRequestedEvent": "app.workflows.digest.events",
    "DigestGraphCompletedEvent": "app.workflows.digest.events",
    "DigestGraphFailedEvent": "app.workflows.digest.events",
    "DocGenCompletedEvent": "app.workflows.digest.events",
    "DocGenFailedEvent": "app.workflows.digest.events",
    "DocGenRequestedEvent": "app.workflows.digest.events",
    "WORKFLOW_EXPORTS": "app.workflows.digest.exports",
    "create_docgen_initial_state": "app.workflows.digest.docgen",
    "create_graph_digest_initial_state": "app.workflows.digest.knowledge_graph",
    "run_docgen_workflow": "app.workflows.digest.docgen",
    "run_graph_digest_workflow": "app.workflows.digest.knowledge_graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
