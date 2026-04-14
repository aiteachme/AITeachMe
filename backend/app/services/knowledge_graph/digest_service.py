"""Knowledge-graph domain wrapper for graph build services."""

from app.services.knowledge_docs.digest_service import (
    run_graph_build_background,
    run_graph_digest_background,
)

__all__ = [
    "run_graph_build_background",
    "run_graph_digest_background",
]
