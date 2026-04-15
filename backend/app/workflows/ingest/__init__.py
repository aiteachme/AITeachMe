"""Ingest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "IngestEnhanceState",
    "IngestParseState",
    "build_deep_enhance_graph",
    "build_fast_parse_graph",
    "build_parse_file_graph",
    "create_parse_file_initial_state",
    "get_langgraph_dev_deep_enhance_graph",
    "get_langgraph_dev_fast_parse_graph",
    "run_parse_file_workflow",
]

_ATTR_TO_MODULE = {
    "IngestEnhanceState": "app.workflows.ingest.deep_enhance.state",
    "IngestParseState": "app.workflows.ingest.fast_parse.state",
    "build_deep_enhance_graph": "app.workflows.ingest.deep_enhance.graph",
    "build_fast_parse_graph": "app.workflows.ingest.fast_parse.graph",
    "build_parse_file_graph": "app.workflows.ingest.graph",
    "create_parse_file_initial_state": "app.workflows.ingest.runtime",
    "get_langgraph_dev_deep_enhance_graph": "app.workflows.ingest.deep_enhance.graph",
    "get_langgraph_dev_fast_parse_graph": "app.workflows.ingest.fast_parse.graph",
    "run_parse_file_workflow": "app.workflows.ingest.runtime",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
