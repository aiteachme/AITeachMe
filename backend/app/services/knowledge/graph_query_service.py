"""Knowledge graph read services backed by the new schema."""

from __future__ import annotations

from sqlmodel import Session, or_, select

from app.core.exceptions import KnowledgeChunkNotFoundError, KnowledgeNodeNotFoundError
from app.models import (
    ExamPaperItem,
    KnowledgeAlias,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeEvidence,
    KnowledgeNode,
    QuestionTemplate,
    RawFile,
    RetrievalChunk,
    Subject,
    TeachingUnit,
)
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


def _get_subject_id(session: Session, subject: str) -> int | None:
    record = session.exec(select(Subject).where(Subject.slug == subject)).first()
    return record.id if record is not None else None


def _build_node_response(subject: str, node: KnowledgeNode) -> KnowledgeNodeResponse:
    return KnowledgeNodeResponse(
        id=int(node.id or 0),
        subject=subject,
        node_type=node.node_type,
        canonical_name=node.canonical_name,
        status=node.status,
        confidence=node.confidence,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def get_graph_nodes(
    session: Session,
    *,
    subject: str,
    node_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeNodeResponse]:
    """Return paginated knowledge nodes for one subject."""

    subject_id = _get_subject_id(session, subject)
    if subject_id is None:
        return build_paginated_data(items=[], page=page, size=size, total=0)

    offset = (page - 1) * size
    stmt = select(KnowledgeNode).where(KnowledgeNode.subject_id == subject_id)
    count_stmt = select(KnowledgeNode).where(KnowledgeNode.subject_id == subject_id)
    if node_type:
        stmt = stmt.where(KnowledgeNode.node_type == node_type)
        count_stmt = count_stmt.where(KnowledgeNode.node_type == node_type)

    total = len(list(session.exec(count_stmt).all()))
    rows = list(
        session.exec(
            stmt.order_by(KnowledgeNode.updated_at.desc()).offset(offset).limit(size)  # type: ignore[union-attr]
        ).all()
    )
    return build_paginated_data(
        items=[_build_node_response(subject, node) for node in rows],
        page=page,
        size=size,
        total=total,
    )


def get_graph_node_detail(session: Session, *, subject: str, node_id: int) -> KnowledgeNodeDetailResponse:
    """Return detail for one knowledge node."""

    subject_id = _get_subject_id(session, subject)
    node = session.get(KnowledgeNode, node_id)
    if node is None or subject_id is None or node.subject_id != subject_id:
        raise KnowledgeNodeNotFoundError(node_id)

    aliases_raw = list(
        session.exec(
            select(KnowledgeAlias)
            .where(KnowledgeAlias.node_id == node_id)
            .order_by(KnowledgeAlias.is_primary.desc(), KnowledgeAlias.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    aliases = [
        AliasItem(
            id=int(alias.id or 0),
            alias=alias.alias,
            language=alias.language,
            source=alias.source,
            confidence=alias.confidence,
            is_primary=alias.is_primary,
        )
        for alias in aliases_raw
    ]

    evidence_raw = list(
        session.exec(
            select(KnowledgeEvidence)
            .where(KnowledgeEvidence.node_id == node_id, KnowledgeEvidence.is_active.is_(True))
            .order_by(KnowledgeEvidence.confidence.desc(), KnowledgeEvidence.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    retrieval_chunk_ids = [item.retrieval_chunk_id for item in evidence_raw]
    chunks = {
        int(chunk.id): chunk
        for chunk in session.exec(
            select(RetrievalChunk).where(RetrievalChunk.id.in_(retrieval_chunk_ids))  # type: ignore[union-attr]
        ).all()
        if chunk.id is not None
    }
    evidence = [
        EvidenceSummary(
            id=int(item.id or 0),
            document_id=chunks[item.retrieval_chunk_id].source_id if item.retrieval_chunk_id in chunks else 0,
            chunk_id=item.retrieval_chunk_id,
            quote_text=item.quote_text,
            evidence_role=item.evidence_role,
            field_scope=item.field_scope,
            confidence=item.confidence,
        )
        for item in evidence_raw
    ]

    edges_raw = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject_id == subject_id,
                or_(
                    KnowledgeEdge.source_node_id == node_id,
                    KnowledgeEdge.target_node_id == node_id,
                ),
            )
        ).all()
    )
    other_node_ids = {
        edge.target_node_id if edge.source_node_id == node_id else edge.source_node_id
        for edge in edges_raw
    }
    other_nodes = {
        int(other.id): other
        for other in session.exec(
            select(KnowledgeNode).where(KnowledgeNode.id.in_(other_node_ids))  # type: ignore[union-attr]
        ).all()
        if other.id is not None
    }
    incident_edges: list[IncidentEdgeItem] = []
    for edge in edges_raw:
        other_id = edge.target_node_id if edge.source_node_id == node_id else edge.source_node_id
        other_node = other_nodes.get(other_id)
        incident_edges.append(
            IncidentEdgeItem(
                id=int(edge.id or 0),
                edge_type=edge.edge_type,
                direction="outgoing" if edge.source_node_id == node_id else "incoming",
                other_node_id=other_id,
                other_node_name=other_node.canonical_name if other_node is not None else f"node#{other_id}",
                other_node_type=other_node.node_type if other_node is not None else "unknown",
                confidence=edge.confidence,
            )
        )

    return KnowledgeNodeDetailResponse(
        id=int(node.id or 0),
        subject=subject,
        node_type=node.node_type,
        canonical_name=node.canonical_name,
        normalized_name=node.normalized_name,
        status=node.status,
        confidence=node.confidence,
        current_revision=NodeRevisionItem(
            title=node.canonical_name,
            summary=node.summary,
            body=node.body,
        ),
        aliases=aliases,
        evidence=evidence,
        incident_edges=incident_edges,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def get_full_graph(session: Session, *, subject: str) -> FullGraphResponse:
    """Return the full graph payload used by overview and graph pages."""

    subject_id = _get_subject_id(session, subject)
    if subject_id is None:
        return FullGraphResponse()

    nodes_raw = list(
        session.exec(
            select(KnowledgeNode)
            .where(KnowledgeNode.subject_id == subject_id)
            .order_by(KnowledgeNode.updated_at.desc())  # type: ignore[union-attr]
        ).all()
    )
    edges_raw = list(
        session.exec(
            select(KnowledgeEdge)
            .where(KnowledgeEdge.subject_id == subject_id)
            .order_by(KnowledgeEdge.id.asc())  # type: ignore[union-attr]
        ).all()
    )
    return FullGraphResponse(
        nodes=[_build_node_response(subject, node) for node in nodes_raw],
        edges=[
            GraphEdgeResponse(
                id=int(edge.id or 0),
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                confidence=edge.confidence,
            )
            for edge in edges_raw
        ],
    )


def _resolve_chunk_document_title(session: Session, chunk: RetrievalChunk) -> str:
    if chunk.source_type == "raw_file":
        raw_file = session.get(RawFile, chunk.source_id)
        return raw_file.original_filename if raw_file is not None else f"raw_file#{chunk.source_id}"
    if chunk.source_type == "knowledge_document":
        document = session.get(KnowledgeDocument, chunk.source_id)
        return document.title if document is not None else f"knowledge_document#{chunk.source_id}"
    if chunk.source_type == "knowledge_node":
        node = session.get(KnowledgeNode, chunk.source_id)
        return node.canonical_name if node is not None else f"knowledge_node#{chunk.source_id}"
    if chunk.source_type == "teaching_unit":
        unit = session.get(TeachingUnit, chunk.source_id)
        return unit.canonical_name if unit is not None else f"teaching_unit#{chunk.source_id}"
    if chunk.source_type == "question_template":
        template = session.get(QuestionTemplate, chunk.source_id)
        return template.stem if template is not None else f"question_template#{chunk.source_id}"
    if chunk.source_type == "exam_paper_item":
        item = session.get(ExamPaperItem, chunk.source_id)
        return item.snapshot_stem if item is not None else f"exam_paper_item#{chunk.source_id}"
    return f"{chunk.source_type}#{chunk.source_id}"


def get_chunk_context(
    session: Session,
    *,
    subject: str,
    chunk_id: int,
) -> ChunkContextResponse:
    """Return full chunk context for one citation."""

    subject_id = _get_subject_id(session, subject)
    chunk = session.get(RetrievalChunk, chunk_id)
    if chunk is None or subject_id is None or chunk.subject_id != subject_id:
        raise KnowledgeChunkNotFoundError(chunk_id)

    return ChunkContextResponse(
        chunk_id=int(chunk.id or 0),
        document_id=chunk.source_id,
        document_title=_resolve_chunk_document_title(session, chunk),
        chunk_title=chunk.title,
        chunk_header_path=chunk.header_path,
        chunk_content=chunk.content,
    )


__all__ = [
    "get_chunk_context",
    "get_full_graph",
    "get_graph_node_detail",
    "get_graph_nodes",
]
