"""Digest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "DocGenState",
    "KGDigestState",
    "build_docgen_graph",
    "build_kg_digest_graph",
    "create_docgen_initial_state",
    "create_graph_digest_initial_state",
    "run_docgen_workflow",
    "run_graph_digest_workflow",
]

_ATTR_TO_MODULE = {
    "DocGenState": "app.workflows.digest.docgen.state",
    "KGDigestState": "app.workflows.digest.knowledge_graph.state",
    "build_docgen_graph": "app.workflows.digest.docgen.graph",
    "build_kg_digest_graph": "app.workflows.digest.knowledge_graph.graph",
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
