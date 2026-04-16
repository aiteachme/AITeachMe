"""Knowledge graph domain entrypoint."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "KnowledgeGraphBuildService",
    "KnowledgeGraphModule",
    "KnowledgeGraphQueryService",
    "KnowledgeGraphMigrationReport",
    "KnowledgeGraphReleaseSnapshot",
    "KnowledgeSyncReport",
    "enable_computable_textbook_rollout",
    "get_release_snapshot",
    "normalize_knowledge_graph",
    "rollback_computable_textbook_rollout",
    "run_graph_build_background",
    "run_graph_digest_background",
    "sync_markdown_knowledge_graph",
]

_ATTR_TO_MODULE = {
    "KnowledgeGraphBuildService": "app.workflows.digest.application.knowledge_graph.build",
    "KnowledgeGraphModule": "app.workflows.digest.application.knowledge_graph.module",
    "KnowledgeGraphQueryService": "app.workflows.digest.application.knowledge_graph.query",
    "KnowledgeGraphMigrationReport": "app.workflows.digest.application.knowledge_graph.migration",
    "KnowledgeGraphReleaseSnapshot": "app.workflows.digest.application.knowledge_graph.release",
    "KnowledgeSyncReport": "app.workflows.digest.application.knowledge_graph.incremental_sync",
    "enable_computable_textbook_rollout": "app.workflows.digest.application.knowledge_graph.release",
    "get_release_snapshot": "app.workflows.digest.application.knowledge_graph.release",
    "normalize_knowledge_graph": "app.workflows.digest.application.knowledge_graph.migration",
    "rollback_computable_textbook_rollout": "app.workflows.digest.application.knowledge_graph.release",
    "run_graph_build_background": "app.workflows.digest.application.knowledge_graph.digest_service",
    "run_graph_digest_background": "app.workflows.digest.application.knowledge_graph.digest_service",
    "sync_markdown_knowledge_graph": "app.workflows.digest.application.knowledge_graph.incremental_sync",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
