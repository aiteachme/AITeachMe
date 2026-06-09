"""Ingest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "IngestParseGraphInput",
    "IngestParseGraphOutput",
    "IngestParseState",
    "WORKFLOW_EXPORTS",
    "build_fast_parse_graph",
    "create_parse_file_initial_state",
    "get_langgraph_dev_fast_parse_graph",
    "recover_stalled_enhancements",
    "run_parse_file_workflow",
]

_ATTR_TO_MODULE = {
    "IngestParseGraphInput": "app.workflows.ingest.parsing.state",
    "IngestParseGraphOutput": "app.workflows.ingest.parsing.state",
    "IngestParseState": "app.workflows.ingest.parsing.state",
    "build_fast_parse_graph": "app.workflows.ingest.parsing.graph",
    "create_parse_file_initial_state": "app.workflows.ingest.parsing.graph",
    "get_langgraph_dev_fast_parse_graph": "app.workflows.ingest.parsing.graph",
    "recover_stalled_enhancements": "app.workflows.ingest.parsing.lib.recovery",
    "run_parse_file_workflow": "app.workflows.ingest.parsing.graph",
}


def _load_workflow_exports():
    parse_graph = import_module("app.workflows.ingest.parsing.graph")
    return tuple(getattr(parse_graph, "WORKFLOW_EXPORTS"))


def __getattr__(name: str):
    if name == "WORKFLOW_EXPORTS":
        value = _load_workflow_exports()
        globals()[name] = value
        return value

    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
