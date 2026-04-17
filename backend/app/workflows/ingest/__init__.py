"""Ingest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "IngestEnhanceState",
    "IngestParseState",
    "WORKFLOW_EXPORTS",
    "build_deep_enhance_graph",
    "build_fast_parse_graph",
    "build_parse_file_graph",
    "create_parse_file_initial_state",
    "get_langgraph_dev_deep_enhance_graph",
    "get_langgraph_dev_fast_parse_graph",
    "recover_stalled_enhancements",
    "run_parse_file_workflow",
]

_ATTR_TO_MODULE = {
    "IngestEnhanceState": "app.workflows.ingest.deep_enhance.state",
    "IngestParseState": "app.workflows.ingest.fast_parse.state",
    "build_deep_enhance_graph": "app.workflows.ingest.deep_enhance.graph",
    "build_fast_parse_graph": "app.workflows.ingest.fast_parse.graph",
    "build_parse_file_graph": "app.workflows.ingest.fast_parse.graph",
    "create_parse_file_initial_state": "app.workflows.ingest.fast_parse.lib.runtime_helpers",
    "get_langgraph_dev_deep_enhance_graph": "app.workflows.ingest.deep_enhance.graph",
    "get_langgraph_dev_fast_parse_graph": "app.workflows.ingest.fast_parse.graph",
    "recover_stalled_enhancements": "app.workflows.ingest.deep_enhance.lib.recovery",
    "run_parse_file_workflow": "app.workflows.ingest.fast_parse.lib.runtime",
}


def _load_workflow_exports():
    fast_parse_graph = import_module("app.workflows.ingest.fast_parse.graph")
    deep_enhance_graph = import_module("app.workflows.ingest.deep_enhance.graph")
    return (
        *getattr(fast_parse_graph, "WORKFLOW_EXPORTS"),
        *getattr(deep_enhance_graph, "WORKFLOW_EXPORTS"),
    )


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
