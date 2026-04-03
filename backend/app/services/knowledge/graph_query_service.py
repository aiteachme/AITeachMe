"""图谱查询服务层：节点查询、节点详情、全图、证据上下文。"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.shared.infra.exceptions import (
    KnowledgeChunkNotFoundError,
    KnowledgeNodeNotFoundError,
)
from app.models.knowledge_graph import KnowledgeNode
from app.repositories import kg_repo, knowledge_repo
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.knowledge import (
    AliasItem,
    ChunkContextResponse,
    EvidenceSummary,
    FullGraphResponse,
    GraphEdgeResponse,
    IncidentEdgeItem,
    KnowledgeNodeDetailResponse,
    KnowledgeNodeResponse,
    NodeRevisionItem,
)

logger = structlog.get_logger()


def get_graph_nodes(
    session: Session,
    *,
    subject: str,
    node_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeNodeResponse]:
    """分页查询知识节点。"""
    offset = (page - 1) * size
    nodes, total = kg_repo.list_nodes_by_subject(
        session, subject, node_type=node_type, limit=size, offset=offset,
    )
    items = [
        KnowledgeNodeResponse(
            id=n.id,  # type: ignore[arg-type]
            subject=n.subject,
            node_type=n.node_type,
            canonical_name=n.canonical_name,
            status=n.status,
            confidence=n.confidence,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in nodes
    ]
    return build_paginated_data(items=items, page=page, size=size, total=total)


def get_graph_node_detail(
    session: Session, *, subject: str, node_id: int
) -> KnowledgeNodeDetailResponse:
    """节点详情：base info + revision + aliases + evidence + incident edges。"""
    result = kg_repo.get_node_with_current_revision(session, node_id)
    if result is None:
        raise KnowledgeNodeNotFoundError(node_id)

    node, revision = result
    if node.subject != subject:
        raise KnowledgeNodeNotFoundError(node_id)

    # 当前修订
    current_rev = NodeRevisionItem(
        title=revision.title,
        summary=revision.summary,
        body=revision.body,
    )

    # 别名
    aliases_raw = kg_repo.list_aliases_by_node(session, node_id)
    aliases = [
        AliasItem(
            id=a.id,  # type: ignore[arg-type]
            alias=a.alias,
            language=a.language,
            source=a.source,
            confidence=a.confidence,
            is_primary=a.is_primary,
        )
        for a in aliases_raw
    ]

    # 活跃证据
    evidence_raw = kg_repo.list_evidence_by_entity(session, "node", node_id)
    evidence = [
        EvidenceSummary(
            id=e.id,  # type: ignore[arg-type]
            document_id=e.document_id,
            chunk_id=e.chunk_id,
            quote_text=e.quote_text,
            evidence_role=e.evidence_role,
            field_scope=e.field_scope,
            confidence=e.confidence,
        )
        for e in evidence_raw
    ]

    # 关联边
    edges_raw = kg_repo.list_edges_by_node(session, node_id)
    incident_edges: list[IncidentEdgeItem] = []
    for edge in edges_raw:
        if edge.source_node_id == node_id:
            other_id = edge.target_node_id
            direction = "outgoing"
        else:
            other_id = edge.source_node_id
            direction = "incoming"

        other_node = session.get(KnowledgeNode, other_id)
        other_name = other_node.canonical_name if other_node else f"node#{other_id}"
        other_type = other_node.node_type if other_node else "unknown"

        incident_edges.append(
            IncidentEdgeItem(
                id=edge.id,  # type: ignore[arg-type]
                edge_type=edge.edge_type,
                direction=direction,
                other_node_id=other_id,
                other_node_name=other_name,
                other_node_type=other_type,
                confidence=edge.confidence,
            )
        )

    return KnowledgeNodeDetailResponse(
        id=node.id,  # type: ignore[arg-type]
        subject=node.subject,
        node_type=node.node_type,
        canonical_name=node.canonical_name,
        normalized_name=node.normalized_name,
        status=node.status,
        confidence=node.confidence,
        current_revision=current_rev,
        aliases=aliases,
        evidence=evidence,
        incident_edges=incident_edges,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def get_full_graph(
    session: Session, *, subject: str
) -> FullGraphResponse:
    """返回学科下所有 active 节点 + 边，用于力导向图可视化。"""
    nodes_raw, _ = kg_repo.list_nodes_by_subject(
        session, subject, limit=5000, offset=0,
    )
    edges_raw = kg_repo.list_all_edges_by_subject(session, subject)

    nodes = [
        KnowledgeNodeResponse(
            id=n.id,  # type: ignore[arg-type]
            subject=n.subject,
            node_type=n.node_type,
            canonical_name=n.canonical_name,
            status=n.status,
            confidence=n.confidence,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in nodes_raw
    ]
    edges = [
        GraphEdgeResponse(
            id=e.id,  # type: ignore[arg-type]
            source_node_id=e.source_node_id,
            target_node_id=e.target_node_id,
            edge_type=e.edge_type,
            weight=e.weight,
            confidence=e.confidence,
        )
        for e in edges_raw
    ]
    return FullGraphResponse(nodes=nodes, edges=edges)


def get_chunk_context(
    session: Session,
    *,
    subject: str,
    chunk_id: int,
) -> ChunkContextResponse:
    """Return raw chunk context for one chat citation."""

    chunk = knowledge_repo.get_chunk_by_id(session, chunk_id)
    if chunk is None:
        raise KnowledgeChunkNotFoundError(chunk_id)

    document = knowledge_repo.get_document_by_id(session, chunk.document_id)
    if document is None or document.subject != subject:
        raise KnowledgeChunkNotFoundError(chunk_id)

    return ChunkContextResponse(
        chunk_id=chunk.id,  # type: ignore[arg-type]
        document_id=document.id,  # type: ignore[arg-type]
        document_title=document.filename,
        chunk_title=chunk.title,
        chunk_header_path=chunk.header_path,
        chunk_content=chunk.content,
    )
