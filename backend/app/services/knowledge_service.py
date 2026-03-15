"""
知识查询编排 — 大纲树构建、文档分页列表
"""

from __future__ import annotations

from sqlmodel import Session

from app.repositories.knowledge_repo import (
    list_graph_nodes_by_subject,
    list_knowledge_by_subject,
    get_graph_nodes_by_knowledge_id,
)
from app.repositories.models import Knowledge, KnowledgeGraphNode
from app.schemas.knowledge import OutlineNode, OutlineResponse


def _build_tree(nodes: list[KnowledgeGraphNode]) -> list[OutlineNode]:
    """从扁平 KnowledgeGraphNode 列表构建树结构。"""
    node_map: dict[int, OutlineNode] = {}
    roots: list[OutlineNode] = []

    for n in nodes:
        node_map[n.id] = OutlineNode(  # type: ignore[arg-type]
            id=n.id,  # type: ignore[arg-type]
            title=n.title,
            level=n.level,
            children=[],
        )

    for n in nodes:
        outline_node = node_map[n.id]  # type: ignore[index]
        if n.parent_id is not None and n.parent_id in node_map:
            node_map[n.parent_id].children.append(outline_node)
        else:
            roots.append(outline_node)

    return roots


def get_outlines(session: Session, subject: str) -> list[OutlineResponse]:
    """返回该 subject 下所有文档的大纲树。"""
    # 获取所有 knowledge
    knowledges, _ = list_knowledge_by_subject(session, subject, limit=10000, offset=0)

    results: list[OutlineResponse] = []
    for k in knowledges:
        nodes = get_graph_nodes_by_knowledge_id(session, k.id)  # type: ignore[arg-type]
        tree = _build_tree(nodes)
        results.append(
            OutlineResponse(
                knowledge_id=k.id,  # type: ignore[arg-type]
                title=k.title,
                nodes=tree,
            )
        )
    return results


def get_documents(
    session: Session, subject: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[Knowledge], int]:
    """分页列表文档。"""
    return list_knowledge_by_subject(session, subject, limit=limit, offset=offset)
