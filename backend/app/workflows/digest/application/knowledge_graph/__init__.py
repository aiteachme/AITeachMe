"""Compatibility re-exports for legacy knowledge-graph imports."""

from app.workflows.digest.knowledge_graph import (
    KnowledgeGraphBuildService,
    KnowledgeGraphModule,
    KnowledgeGraphQueryService,
    run_graph_build_background,
    run_graph_digest_background,
)

__all__ = [
    "KnowledgeGraphBuildService",
    "KnowledgeGraphModule",
    "KnowledgeGraphQueryService",
    "run_graph_build_background",
    "run_graph_digest_background",
]
