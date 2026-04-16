"""Digest knowledge-graph workflow package."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "KnowledgeDigestState",
    "build_knowledge_digest_graph",
    "create_graph_digest_initial_state",
]

_ATTR_TO_MODULE = {
    "KnowledgeDigestState": "app.workflows.digest.knowledge_graph.state",
    "build_knowledge_digest_graph": "app.workflows.digest.knowledge_graph.graph",
    "create_graph_digest_initial_state": "app.workflows.digest.knowledge_graph.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
