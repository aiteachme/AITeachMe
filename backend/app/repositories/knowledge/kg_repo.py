"""Knowledge graph repository helpers."""

from __future__ import annotations

import json

from sqlmodel import Session, func, or_, select

from app.models.knowledge_graph import (
    EdgeRevision,
    EvidenceLink,
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeUnit,
    KnowledgeRevision,
)
from app.utils.time import utcnow
from app.models.kg_taxonomy import (
    normalize_knowledge_unit_type,
    normalize_relation_type,
    normalize_type_source,
    validate_relation_direction,
)


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


def acquire_subject_build_lock(
    session: Session,
    subject: str,
    job_id: int,
    *,
    ttl_minutes: int = 30,
) -> bool:
    del session, subject, job_id, ttl_minutes
    return True


def release_subject_build_lock(session: Session, subject: str) -> None:
    del session, subject


def create_knowledge_unit(
    session: Session,
    knowledge_unit: KnowledgeUnit,
    *,
    auto_commit: bool = True,
) -> KnowledgeUnit:
    knowledge_unit.node_type = normalize_knowledge_unit_type(knowledge_unit.node_type)
    knowledge_unit.type_source = normalize_type_source(getattr(knowledge_unit, "type_source", None))
    knowledge_unit.type_confidence = max(0.0, min(1.0, float(knowledge_unit.type_confidence)))
    session.add(knowledge_unit)
    if auto_commit:
        session.commit()
        session.refresh(knowledge_unit)
    else:
        session.flush()
    return knowledge_unit


def get_knowledge_unit_by_id(session: Session, knowledge_unit_id: int) -> KnowledgeUnit | None:
    return session.get(KnowledgeUnit, knowledge_unit_id)


def find_knowledge_unit_by_normalized_name(
    session: Session,
    subject: str,
    normalized_name: str,
    knowledge_unit_type: str,
    *,
    include_pending: bool = True,
) -> KnowledgeUnit | None:
    knowledge_unit_type = normalize_knowledge_unit_type(knowledge_unit_type)
    allowed = ["active"]
    if include_pending:
        allowed.append("pending")
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.subject == subject,
        KnowledgeUnit.normalized_name == normalized_name,
        KnowledgeUnit.node_type == knowledge_unit_type,
        KnowledgeUnit.status.in_(allowed),
    )
    return session.exec(stmt).first()


def find_knowledge_units_by_alias(
    session: Session,
    subject: str,
    normalized_alias: str,
    knowledge_unit_type: str,
) -> list[KnowledgeUnit]:
    knowledge_unit_type = normalize_knowledge_unit_type(knowledge_unit_type)
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.subject == subject,
        KnowledgeUnit.node_type == knowledge_unit_type,
        KnowledgeUnit.status.in_(["active", "pending"]),
    )
    rows = list(session.exec(stmt).all())
    matched: list[KnowledgeUnit] = []
    for item in rows:
        aliases = _load_json_list(item.aliases_json)
        if any(alias.get("normalized_alias") == normalized_alias for alias in aliases):
            matched.append(item)
    return matched


def list_knowledge_units_by_subject(
    session: Session,
    subject: str,
    *,
    knowledge_unit_type: str | None = None,
    status: str | None = "active",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[KnowledgeUnit], int]:
    base = select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)
    count_base = select(func.count(KnowledgeUnit.id)).where(KnowledgeUnit.subject == subject)

    if status is not None:
        base = base.where(KnowledgeUnit.status == status)
        count_base = count_base.where(KnowledgeUnit.status == status)
    if knowledge_unit_type is not None:
        knowledge_unit_type = normalize_knowledge_unit_type(knowledge_unit_type)
        base = base.where(KnowledgeUnit.node_type == knowledge_unit_type)
        count_base = count_base.where(KnowledgeUnit.node_type == knowledge_unit_type)

    total: int = session.exec(count_base).one()
    rows = list(session.exec(base.offset(offset).limit(limit).order_by(KnowledgeUnit.id)).all())
    return rows, total


def get_knowledge_unit_with_current_revision(
    session: Session,
    knowledge_unit_id: int,
) -> tuple[KnowledgeUnit, KnowledgeRevision] | None:
    knowledge_unit = session.get(KnowledgeUnit, knowledge_unit_id)
    if knowledge_unit is None:
        return None
    revision = KnowledgeRevision(
        id=knowledge_unit.current_revision_id,
        node_id=knowledge_unit.id or 0,
        revision_no=1,
        title=knowledge_unit.canonical_name,
        summary=knowledge_unit.summary,
        body=knowledge_unit.body_markdown or knowledge_unit.body,
        revision_reason="materialized",
        is_current=True,
        created_at=knowledge_unit.updated_at,
    )
    return knowledge_unit, revision


def create_alias(
    session: Session,
    alias: KnowledgeAlias,
    *,
    auto_commit: bool = True,
) -> KnowledgeAlias:
    node = session.get(KnowledgeUnit, alias.node_id)
    if node is None:
        return alias

    payload = _load_json_list(node.aliases_json)
    payload.append(
        {
            "alias": alias.alias,
            "normalized_alias": alias.normalized_alias,
            "language": alias.language,
            "source": alias.source,
            "confidence": alias.confidence,
            "is_primary": alias.is_primary,
            "status": alias.status,
        }
    )
    node.aliases_json = _dump_json_list(payload)
    session.add(node)
    if auto_commit:
        session.commit()
    return alias


def find_alias(session: Session, subject: str, normalized_alias: str) -> list[KnowledgeAlias]:
    nodes = list(
        session.exec(
            select(KnowledgeUnit).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status.in_(["active", "pending"]),
            )
        ).all()
    )
    matched: list[KnowledgeAlias] = []
    synthetic_id = 1
    for node in nodes:
        for alias in _load_json_list(node.aliases_json):
            if alias.get("normalized_alias") != normalized_alias:
                continue
            matched.append(
                KnowledgeAlias(
                    id=synthetic_id,
                    node_id=node.id or 0,
                    alias=str(alias.get("alias", "")),
                    normalized_alias=str(alias.get("normalized_alias", "")),
                    language=str(alias.get("language", "zh")),
                    source=str(alias.get("source", "llm")),
                    confidence=float(alias.get("confidence", 1.0)),
                    is_primary=bool(alias.get("is_primary", False)),
                    status=str(alias.get("status", "active")),
                )
            )
            synthetic_id += 1
    return matched


def list_aliases_by_knowledge_unit(session: Session, knowledge_unit_id: int) -> list[KnowledgeAlias]:
    knowledge_unit = session.get(KnowledgeUnit, knowledge_unit_id)
    if knowledge_unit is None:
        return []

    items: list[KnowledgeAlias] = []
    for index, alias in enumerate(_load_json_list(knowledge_unit.aliases_json), start=1):
        items.append(
            KnowledgeAlias(
                id=index,
                node_id=knowledge_unit_id,
                alias=str(alias.get("alias", "")),
                normalized_alias=str(alias.get("normalized_alias", "")),
                language=str(alias.get("language", "zh")),
                source=str(alias.get("source", "llm")),
                confidence=float(alias.get("confidence", 1.0)),
                is_primary=bool(alias.get("is_primary", False)),
                status=str(alias.get("status", "active")),
            )
        )
    return items


def create_knowledge_edge(
    session: Session,
    edge: KnowledgeEdge,
    *,
    auto_commit: bool = True,
) -> KnowledgeEdge:
    normalized_relation = normalize_relation_type(edge.edge_type)
    edge.edge_type = normalized_relation.edge_type
    if normalized_relation.swap_endpoints:
        edge.source_node_id, edge.target_node_id = edge.target_node_id, edge.source_node_id
    source_unit = session.get(KnowledgeUnit, edge.source_node_id)
    target_unit = session.get(KnowledgeUnit, edge.target_node_id)
    if source_unit is not None and target_unit is not None and not validate_relation_direction(
        edge_type=edge.edge_type,
        source_type=source_unit.node_type,
        target_type=target_unit.node_type,
    ):
        raise ValueError(
            "invalid knowledge edge direction: "
            f"{edge.edge_type} {source_unit.node_type}->{target_unit.node_type}"
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
    edge_type = normalize_relation_type(edge_type).edge_type
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
    edge_type = normalize_relation_type(edge_type).edge_type
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


def create_knowledge_revision(
    session: Session,
    revision: KnowledgeRevision,
    *,
    auto_commit: bool = True,
) -> KnowledgeRevision:
    node = session.get(KnowledgeUnit, revision.node_id)
    if node is None:
        return revision

    revision.id = node.id
    node.summary = revision.summary
    node.body = revision.body
    node.body_markdown = revision.body
    node.current_revision_id = revision.id
    node.updated_at = utcnow()
    session.add(node)
    if auto_commit:
        session.commit()
    return revision


def deactivate_old_knowledge_unit_revisions(session: Session, knowledge_unit_id: int) -> None:
    del session, knowledge_unit_id


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


def update_digest_job(session: Session, job_id: int, **kwargs: object) -> None:
    del session, job_id, kwargs
