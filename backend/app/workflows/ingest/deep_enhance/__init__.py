"""Deep-enhance ingest chain with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "IngestEnhanceState",
    "build_deep_enhance_graph",
    "get_langgraph_dev_deep_enhance_graph",
]

_ATTR_TO_MODULE = {
    "IngestEnhanceState": "app.workflows.ingest.deep_enhance.state",
    "build_deep_enhance_graph": "app.workflows.ingest.deep_enhance.graph",
    "get_langgraph_dev_deep_enhance_graph": "app.workflows.ingest.deep_enhance.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
