"""Ingest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "INGEST_PARSE_DIAGRAM",
    "IngestParseState",
    "WORKFLOW_DIAGRAMS",
    "build_parse_file_graph",
    "create_parse_file_initial_state",
    "run_parse_file_workflow",
]

_ATTR_TO_MODULE = {
    "INGEST_PARSE_DIAGRAM": "app.workflows.ingest.diagrams",
    "IngestParseState": "app.workflows.ingest.state",
    "WORKFLOW_DIAGRAMS": "app.workflows.ingest.diagrams",
    "build_parse_file_graph": "app.workflows.ingest.graph",
    "create_parse_file_initial_state": "app.workflows.ingest.graph",
    "run_parse_file_workflow": "app.workflows.ingest.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
