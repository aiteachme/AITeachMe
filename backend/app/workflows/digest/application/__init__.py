"""Canonical digest application entrypoints with lazy exports."""

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
    "DigestBuildRequestedEvent": "app.workflows.digest.application.events",
    "DigestGraphCompletedEvent": "app.workflows.digest.application.events",
    "DigestGraphFailedEvent": "app.workflows.digest.application.events",
    "DocGenCompletedEvent": "app.workflows.digest.application.events",
    "DocGenFailedEvent": "app.workflows.digest.application.events",
    "DocGenRequestedEvent": "app.workflows.digest.application.events",
    "WORKFLOW_EXPORTS": "app.workflows.digest.application.exports",
    "create_docgen_initial_state": "app.workflows.digest.application.runtime",
    "create_graph_digest_initial_state": "app.workflows.digest.application.runtime",
    "run_docgen_workflow": "app.workflows.digest.application.runtime",
    "run_graph_digest_workflow": "app.workflows.digest.application.runtime",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
