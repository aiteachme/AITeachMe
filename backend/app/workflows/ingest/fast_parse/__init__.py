"""Fast-parse ingest chain with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "IngestParseState",
    "build_fast_parse_graph",
    "get_langgraph_dev_fast_parse_graph",
]

_ATTR_TO_MODULE = {
    "IngestParseState": "app.workflows.ingest.fast_parse.state",
    "build_fast_parse_graph": "app.workflows.ingest.fast_parse.graph",
    "get_langgraph_dev_fast_parse_graph": "app.workflows.ingest.fast_parse.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
