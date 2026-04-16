"""Knowledge graph domain entrypoint."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "KnowledgeGraphBuildService",
    "KnowledgeGraphModule",
    "KnowledgeGraphQueryService",
    "run_graph_build_background",
    "run_graph_digest_background",
]

_ATTR_TO_MODULE = {
    "KnowledgeGraphBuildService": "app.workflows.digest.application.knowledge_graph.build",
    "KnowledgeGraphModule": "app.workflows.digest.application.knowledge_graph.module",
    "KnowledgeGraphQueryService": "app.workflows.digest.application.knowledge_graph.query",
    "run_graph_build_background": "app.workflows.digest.application.knowledge_graph.digest_service",
    "run_graph_digest_background": "app.workflows.digest.application.knowledge_graph.digest_service",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
