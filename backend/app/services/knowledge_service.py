"""
知识查询编排 — 大纲树构建、文档分页列表
"""

from __future__ import annotations

from sqlmodel import Session

from app.repositories.knowledge_repo import (
    get_graph_nodes_by_knowledge_id,
    list_knowledge_by_subject,
)
from app.repositories.models import Knowledge, KnowledgeGraphNode
from app.schemas.knowledge import OutlineNode, OutlineResponse
from app.services.presenters import require_id, to_outline_response


def _build_tree(nodes: list[KnowledgeGraphNode]) -> list[OutlineNode]:
    """Build a nested outline tree from a flat `KnowledgeGraphNode` list."""

    node_map: dict[int, OutlineNode] = {}
    roots: list[OutlineNode] = []

    for n in nodes:
        node_id = require_id(n.id, "KnowledgeGraphNode.id")
        node_map[node_id] = OutlineNode(
            id=node_id,
            title=n.title,
            level=n.level,
            children=[],
        )

    for n in nodes:
        node_id = require_id(n.id, "KnowledgeGraphNode.id")
        outline_node = node_map[node_id]
        if n.parent_id is not None and n.parent_id in node_map:
            node_map[n.parent_id].children.append(outline_node)
        else:
            roots.append(outline_node)

    return roots


def get_outlines(session: Session, subject: str) -> list[OutlineResponse]:
    """Return one outline tree response per knowledge document in a subject."""
    knowledges, _ = list_knowledge_by_subject(session, subject, limit=10000, offset=0)

    results: list[OutlineResponse] = []
    for k in knowledges:
        knowledge_id = require_id(k.id, "Knowledge.id")
        nodes = get_graph_nodes_by_knowledge_id(session, knowledge_id)
        tree = _build_tree(nodes)
        results.append(to_outline_response(k, tree))
    return results


def get_documents(
    session: Session, subject: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[Knowledge], int]:
    """Return a paginated list of knowledge documents for one subject."""

    return list_knowledge_by_subject(session, subject, limit=limit, offset=offset)
