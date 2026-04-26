"""Digest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "DocGenState",
    "WORKFLOW_EXPORTS",
    "build_docgen_graph",
    "create_docgen_initial_state",
    "run_docgen_workflow",
    "run_graph_docs_sync_workflow",
]

_ATTR_TO_MODULE = {
    "DocGenState": "app.workflows.digest.docgen.state",
    "WORKFLOW_EXPORTS": "app.workflows.digest.common.exports",
    "build_docgen_graph": "app.workflows.digest.docgen",
    "create_docgen_initial_state": "app.workflows.digest.docgen",
    "run_docgen_workflow": "app.workflows.digest.docgen",
    "run_graph_docs_sync_workflow": "app.workflows.digest.kg_doc_sync",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
