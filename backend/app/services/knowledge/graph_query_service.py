"""Compatibility shim for legacy graph query imports.

Canonical implementation moved to ``app.services.knowledge_graph.query``.
"""

from app.services.knowledge_graph.query import (
    get_chunk_context,
    get_full_graph,
    get_graph_node_detail,
    get_graph_nodes,
)

__all__ = [
    "get_chunk_context",
    "get_full_graph",
    "get_graph_node_detail",
    "get_graph_nodes",
]

