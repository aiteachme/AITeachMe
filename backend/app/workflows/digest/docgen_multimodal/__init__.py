"""Independent multimodal DocGen workflow public surface."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "MultimodalDocGenState",
    "build_multimodal_docgen_graph",
    "create_multimodal_docgen_initial_state",
    "get_langgraph_dev_multimodal_docgen_graph",
    "run_multimodal_docgen_workflow",
]

_ATTR_TO_MODULE = {
    "MultimodalDocGenState": "app.workflows.digest.docgen_multimodal.state",
    "build_multimodal_docgen_graph": "app.workflows.digest.docgen_multimodal.graph",
    "create_multimodal_docgen_initial_state": "app.workflows.digest.docgen_multimodal.graph",
    "get_langgraph_dev_multimodal_docgen_graph": "app.workflows.digest.docgen_multimodal.graph",
    "run_multimodal_docgen_workflow": "app.workflows.digest.docgen_multimodal.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
