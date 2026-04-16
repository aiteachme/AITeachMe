"""Knowledge graph query use-cases."""

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


class KnowledgeGraphQueryService:
    """Query-oriented operations over one subject's knowledge graph."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_graph_nodes(
        self,
        *,
        subject: str,
        node_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PaginatedData[KnowledgeNodeResponse]:
        offset = (page - 1) * size
        nodes, total = kg_repo.list_nodes_by_subject(
            self._session,
            subject,
            node_type=node_type,
            limit=size,
            offset=offset,
        )
        items = [
            KnowledgeNodeResponse(
                id=node.id,  # type: ignore[arg-type]
                subject=node.subject,
                node_type=node.node_type,
                canonical_name=node.canonical_name,
                status=node.status,
                confidence=node.confidence,
                created_at=node.created_at,
                updated_at=node.updated_at,
            )
            for node in nodes
        ]
        return build_paginated_data(items=items, page=page, size=size, total=total)

    def get_graph_node_detail(
        self,
        *,
        subject: str,
        node_id: int,
    ) -> KnowledgeNodeDetailResponse:
        result = kg_repo.get_node_with_current_revision(self._session, node_id)
        if result is None:
            raise KnowledgeNodeNotFoundError(node_id)

        node, revision = result
        if node.subject != subject:
            raise KnowledgeNodeNotFoundError(node_id)

        current_rev = NodeRevisionItem(
            title=revision.title,
            summary=revision.summary,
            body=revision.body,
        )

        aliases_raw = kg_repo.list_aliases_by_node(self._session, node_id)
        aliases = [
            AliasItem(
                id=alias.id,  # type: ignore[arg-type]
                alias=alias.alias,
                language=alias.language,
                source=alias.source,
                confidence=alias.confidence,
                is_primary=alias.is_primary,
            )
            for alias in aliases_raw
        ]

        evidence_raw = kg_repo.list_evidence_by_entity(self._session, "node", node_id)
        evidence = [
            EvidenceSummary(
                id=item.id,  # type: ignore[arg-type]
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                quote_text=item.quote_text,
                evidence_role=item.evidence_role,
                field_scope=item.field_scope,
                confidence=item.confidence,
            )
            for item in evidence_raw
        ]

        edges_raw = kg_repo.list_edges_by_node(self._session, node_id)
        incident_edges: list[IncidentEdgeItem] = []
        for edge in edges_raw:
            if edge.source_node_id == node_id:
                other_id = edge.target_node_id
                direction = "outgoing"
            else:
                other_id = edge.source_node_id
                direction = "incoming"

            other_node = self._session.get(KnowledgeNode, other_id)
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
        self,
        *,
        subject: str,
    ) -> FullGraphResponse:
        nodes_raw, _ = kg_repo.list_nodes_by_subject(
            self._session,
            subject,
            limit=5000,
            offset=0,
        )
        edges_raw = kg_repo.list_all_edges_by_subject(self._session, subject)

        nodes = [
            KnowledgeNodeResponse(
                id=node.id,  # type: ignore[arg-type]
                subject=node.subject,
                node_type=node.node_type,
                canonical_name=node.canonical_name,
                status=node.status,
                confidence=node.confidence,
                created_at=node.created_at,
                updated_at=node.updated_at,
            )
            for node in nodes_raw
        ]
        edges = [
            GraphEdgeResponse(
                id=edge.id,  # type: ignore[arg-type]
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                confidence=edge.confidence,
            )
            for edge in edges_raw
        ]
        return FullGraphResponse(nodes=nodes, edges=edges)

    def get_chunk_context(
        self,
        *,
        subject: str,
        chunk_id: int,
    ) -> ChunkContextResponse:
        chunk = knowledge_repo.get_chunk_by_id(self._session, chunk_id)
        if chunk is None:
            raise KnowledgeChunkNotFoundError(chunk_id)

        document = knowledge_repo.get_document_by_id(self._session, chunk.document_id)
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


def get_graph_nodes(
    session: Session,
    *,
    subject: str,
    node_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeNodeResponse]:
    return KnowledgeGraphQueryService(session).get_graph_nodes(
        subject=subject,
        node_type=node_type,
        page=page,
        size=size,
    )


def get_graph_node_detail(
    session: Session,
    *,
    subject: str,
    node_id: int,
) -> KnowledgeNodeDetailResponse:
    return KnowledgeGraphQueryService(session).get_graph_node_detail(
        subject=subject,
        node_id=node_id,
    )


def get_full_graph(
    session: Session,
    *,
    subject: str,
) -> FullGraphResponse:
    return KnowledgeGraphQueryService(session).get_full_graph(subject=subject)


def get_chunk_context(
    session: Session,
    *,
    subject: str,
    chunk_id: int,
) -> ChunkContextResponse:
    return KnowledgeGraphQueryService(session).get_chunk_context(
        subject=subject,
        chunk_id=chunk_id,
    )


__all__ = [
    "KnowledgeGraphQueryService",
    "get_chunk_context",
    "get_full_graph",
    "get_graph_node_detail",
    "get_graph_nodes",
]
