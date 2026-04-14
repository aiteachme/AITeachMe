"""Knowledge graph domain entrypoint.

This package hosts the subject-facing knowledge graph domain façade and
use-case services. Existing callers may still use compatibility shims under
``app.services.knowledge.*`` during migration.
"""

from app.services.knowledge_graph.build import KnowledgeGraphBuildService
from app.services.knowledge_graph.digest_service import (
    run_graph_build_background,
    run_graph_digest_background,
)
from app.services.knowledge_graph.module import KnowledgeGraphModule
from app.services.knowledge_graph.query import KnowledgeGraphQueryService

__all__ = [
    "KnowledgeGraphBuildService",
    "KnowledgeGraphModule",
    "KnowledgeGraphQueryService",
    "run_graph_build_background",
    "run_graph_digest_background",
]
