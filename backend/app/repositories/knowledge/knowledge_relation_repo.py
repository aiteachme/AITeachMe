"""Knowledge graph relation repository helpers."""

from __future__ import annotations

import json

from sqlmodel import Session, or_, select

from app.models.knowledge_relation import EdgeRevision, EvidenceLink, KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.knowledge_taxonomy import normalize_relation_type, validate_relation_direction
from app.utils.time import utcnow


def _load_json_list(raw: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _dump_json_list(payload: list[dict[str, object]]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def create_knowledge_edge(
    session: Session,
    edge: KnowledgeEdge,
    *,
    auto_commit: bool = True,
) -> KnowledgeEdge:
    edge.edge_type = normalize_relation_type(edge.edge_type)
    source_unit = session.get(KnowledgeUnit, edge.source_node_id)
    target_unit = session.get(KnowledgeUnit, edge.target_node_id)
    if source_unit is not None and target_unit is not None and not validate_relation_direction(
        edge_type=edge.edge_type,
        source_type=source_unit.knowledge_unit_type,
        target_type=target_unit.knowledge_unit_type,
    ):
        raise ValueError(
            "invalid knowledge edge direction: "
            f"{edge.edge_type} {source_unit.knowledge_unit_type}->{target_unit.knowledge_unit_type}"
        )
    session.add(edge)
    if auto_commit:
        session.commit()
        session.refresh(edge)
    else:
        session.flush()
    return edge


def find_edge(
    session: Session,
    source_node_id: int,
    target_node_id: int,
    edge_type: str,
) -> KnowledgeEdge | None:
    edge_type = normalize_relation_type(edge_type)
    stmt = select(KnowledgeEdge).where(
        KnowledgeEdge.source_node_id == source_node_id,
        KnowledgeEdge.target_node_id == target_node_id,
        KnowledgeEdge.edge_type == edge_type,
    )
    return session.exec(stmt).first()


def list_edges_by_knowledge_unit(
    session: Session,
    knowledge_unit_id: int,
    *,
    status: str | None = "active",
) -> list[KnowledgeEdge]:
    stmt = select(KnowledgeEdge).where(
        or_(
            KnowledgeEdge.source_node_id == knowledge_unit_id,
            KnowledgeEdge.target_node_id == knowledge_unit_id,
        )
    )
    if status is not None:
        stmt = stmt.where(KnowledgeEdge.status == status)
    return list(session.exec(stmt).all())


def list_edges_by_type(
    session: Session,
    subject: str,
    edge_type: str,
    *,
    status: str | None = "active",
) -> list[KnowledgeEdge]:
    edge_type = normalize_relation_type(edge_type)
    stmt = select(KnowledgeEdge).where(
        KnowledgeEdge.subject == subject,
        KnowledgeEdge.edge_type == edge_type,
    )
    if status is not None:
        stmt = stmt.where(KnowledgeEdge.status == status)
    return list(session.exec(stmt).all())


def list_all_edges_by_subject(
    session: Session,
    subject: str,
    *,
    status: str | None = "active",
) -> list[KnowledgeEdge]:
    stmt = select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)
    if status is not None:
        stmt = stmt.where(KnowledgeEdge.status == status)
    return list(session.exec(stmt).all())


def create_edge_revision(
    session: Session,
    revision: EdgeRevision,
    *,
    auto_commit: bool = True,
) -> EdgeRevision:
    edge = session.get(KnowledgeEdge, revision.edge_id)
    if edge is None:
        return revision

    revision.id = edge.id
    edge.description = revision.description
    edge.weight = revision.weight
    edge.confidence = revision.confidence
    edge.current_revision_id = revision.id
    edge.updated_at = utcnow()
    session.add(edge)
    if auto_commit:
        session.commit()
    return revision


def deactivate_old_edge_revisions(session: Session, edge_id: int) -> None:
    del session, edge_id


def create_evidence_link(
    session: Session,
    link: EvidenceLink,
    *,
    auto_commit: bool = True,
) -> EvidenceLink:
    payload = {
        "document_id": link.document_id,
        "chunk_id": link.chunk_id,
        "quote_text": link.quote_text,
        "source_span_start": link.source_span_start,
        "source_span_end": link.source_span_end,
        "evidence_role": link.evidence_role,
        "field_scope": link.field_scope,
        "confidence": link.confidence,
        "is_active": link.is_active,
    }

    if link.entity_type == "node":
        node = session.get(KnowledgeUnit, link.entity_id)
        if node is not None:
            refs = _load_json_list(node.evidence_refs_json)
            if payload not in refs:
                refs.append(payload)
            node.evidence_refs_json = _dump_json_list(refs)
            session.add(node)
            if auto_commit:
                session.commit()
    elif link.entity_type == "edge":
        edge = session.get(KnowledgeEdge, link.entity_id)
        if edge is not None:
            refs = _load_json_list(edge.evidence_refs_json)
            if payload not in refs:
                refs.append(payload)
            edge.evidence_refs_json = _dump_json_list(refs)
            session.add(edge)
            if auto_commit:
                session.commit()
    return link


def list_evidence_by_entity(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    is_active: bool | None = True,
) -> list[EvidenceLink]:
    raw_items: list[dict[str, object]]
    if entity_type == "node":
        node = session.get(KnowledgeUnit, entity_id)
        raw_items = [] if node is None else _load_json_list(node.evidence_refs_json)
    else:
        edge = session.get(KnowledgeEdge, entity_id)
        raw_items = [] if edge is None else _load_json_list(edge.evidence_refs_json)

    items: list[EvidenceLink] = []
    for index, item in enumerate(raw_items, start=1):
        active = bool(item.get("is_active", True))
        if is_active is not None and active is not is_active:
            continue
        items.append(
            EvidenceLink(
                id=index,
                subject="",
                entity_type=entity_type,
                entity_id=entity_id,
                document_id=int(item.get("document_id", 0)),
                chunk_id=int(item.get("chunk_id", 0)),
                quote_text=str(item.get("quote_text", "")),
                source_span_start=item.get("source_span_start"),
                source_span_end=item.get("source_span_end"),
                evidence_role=str(item.get("evidence_role", "")),
                field_scope=str(item.get("field_scope", "summary")),
                confidence=float(item.get("confidence", 1.0)),
                is_active=active,
            )
        )
    return items


def count_active_evidence(session: Session, entity_type: str, entity_id: int) -> int:
    return len(list_evidence_by_entity(session, entity_type, entity_id, is_active=True))

