"""Knowledge graph repository helpers backed by the flattened schema."""

from __future__ import annotations

from sqlmodel import Session, func, or_, select

from app.models import (
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeEvidence,
    KnowledgeNode,
    Subject,
)


def _subject_filters(subject: str):
    return (Subject.slug == subject,)


def acquire_subject_build_lock(
    session: Session,
    subject: str,
    job_id: int,
    *,
    ttl_minutes: int = 30,
) -> bool:
    """Compatibility shim after graph build lock table removal."""

    del session, subject, job_id, ttl_minutes
    return True


def release_subject_build_lock(session: Session, subject: str) -> None:
    """Compatibility shim after graph build lock table removal."""

    del session, subject


def create_knowledge_node(session: Session, node: KnowledgeNode) -> KnowledgeNode:
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def get_knowledge_node_by_id(session: Session, node_id: int) -> KnowledgeNode | None:
    return session.get(KnowledgeNode, node_id)


def find_node_by_normalized_name(
    session: Session,
    subject: str,
    normalized_name: str,
    node_type: str,
    *,
    include_pending: bool = True,
) -> KnowledgeNode | None:
    allowed = ["active"]
    if include_pending:
        allowed.append("pending")
    stmt = (
        select(KnowledgeNode)
        .join(Subject, KnowledgeNode.subject_id == Subject.id)
        .where(
            *_subject_filters(subject),
            KnowledgeNode.normalized_name == normalized_name,
            KnowledgeNode.node_type == node_type,
            KnowledgeNode.status.in_(allowed),  # type: ignore[union-attr]
        )
    )
    return session.exec(stmt).first()


def find_nodes_by_alias(
    session: Session,
    subject: str,
    normalized_alias: str,
    node_type: str,
) -> list[KnowledgeNode]:
    stmt = (
        select(KnowledgeNode)
        .join(Subject, KnowledgeNode.subject_id == Subject.id)
        .join(KnowledgeAlias, KnowledgeAlias.node_id == KnowledgeNode.id)
        .where(
            *_subject_filters(subject),
            KnowledgeNode.node_type == node_type,
            KnowledgeAlias.normalized_alias == normalized_alias,
            KnowledgeAlias.status == "active",
            KnowledgeNode.status.in_(["active", "pending"]),  # type: ignore[union-attr]
        )
    )
    return list(session.exec(stmt).all())


def list_nodes_by_subject(
    session: Session,
    subject: str,
    *,
    node_type: str | None = None,
    status: str | None = "active",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[KnowledgeNode], int]:
    base = (
        select(KnowledgeNode)
        .join(Subject, KnowledgeNode.subject_id == Subject.id)
        .where(*_subject_filters(subject))
    )
    count_base = (
        select(func.count(KnowledgeNode.id))
        .join(Subject, KnowledgeNode.subject_id == Subject.id)
        .where(*_subject_filters(subject))
    )

    if status is not None:
        base = base.where(KnowledgeNode.status == status)
        count_base = count_base.where(KnowledgeNode.status == status)
    if node_type is not None:
        base = base.where(KnowledgeNode.node_type == node_type)
        count_base = count_base.where(KnowledgeNode.node_type == node_type)

    total: int = session.exec(count_base).one()
    rows = list(
        session.exec(base.offset(offset).limit(limit).order_by(KnowledgeNode.id.asc())).all()
    )
    return rows, total


def create_alias(session: Session, alias: KnowledgeAlias) -> KnowledgeAlias:
    session.add(alias)
    session.commit()
    session.refresh(alias)
    return alias


def find_alias(session: Session, subject: str, normalized_alias: str) -> list[KnowledgeAlias]:
    stmt = (
        select(KnowledgeAlias)
        .join(KnowledgeNode, KnowledgeAlias.node_id == KnowledgeNode.id)
        .join(Subject, KnowledgeNode.subject_id == Subject.id)
        .where(
            *_subject_filters(subject),
            KnowledgeAlias.normalized_alias == normalized_alias,
            KnowledgeAlias.status == "active",
        )
    )
    return list(session.exec(stmt).all())


def list_aliases_by_node(session: Session, node_id: int) -> list[KnowledgeAlias]:
    stmt = select(KnowledgeAlias).where(KnowledgeAlias.node_id == node_id)
    return list(session.exec(stmt).all())


def create_knowledge_edge(session: Session, edge: KnowledgeEdge) -> KnowledgeEdge:
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


def find_edge(
    session: Session,
    source_node_id: int,
    target_node_id: int,
    edge_type: str,
) -> KnowledgeEdge | None:
    stmt = select(KnowledgeEdge).where(
        KnowledgeEdge.source_node_id == source_node_id,
        KnowledgeEdge.target_node_id == target_node_id,
        KnowledgeEdge.edge_type == edge_type,
    )
    return session.exec(stmt).first()


def list_edges_by_node(
    session: Session,
    node_id: int,
    *,
    status: str | None = "active",
) -> list[KnowledgeEdge]:
    stmt = select(KnowledgeEdge).where(
        or_(
            KnowledgeEdge.source_node_id == node_id,
            KnowledgeEdge.target_node_id == node_id,
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
    stmt = (
        select(KnowledgeEdge)
        .join(Subject, KnowledgeEdge.subject_id == Subject.id)
        .where(*_subject_filters(subject), KnowledgeEdge.edge_type == edge_type)
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
    stmt = (
        select(KnowledgeEdge)
        .join(Subject, KnowledgeEdge.subject_id == Subject.id)
        .where(*_subject_filters(subject))
    )
    if status is not None:
        stmt = stmt.where(KnowledgeEdge.status == status)
    return list(session.exec(stmt).all())


def create_knowledge_evidence(session: Session, evidence: KnowledgeEvidence) -> KnowledgeEvidence:
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return evidence


def list_evidence_by_entity(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    is_active: bool | None = True,
) -> list[KnowledgeEvidence]:
    stmt = select(KnowledgeEvidence)
    if entity_type == "node":
        stmt = stmt.where(KnowledgeEvidence.node_id == entity_id)
    else:
        stmt = stmt.where(KnowledgeEvidence.edge_id == entity_id)
    if is_active is not None:
        stmt = stmt.where(KnowledgeEvidence.is_active == is_active)
    return list(session.exec(stmt).all())


def count_active_evidence(session: Session, entity_type: str, entity_id: int) -> int:
    stmt = select(func.count(KnowledgeEvidence.id))
    if entity_type == "node":
        stmt = stmt.where(KnowledgeEvidence.node_id == entity_id)
    else:
        stmt = stmt.where(KnowledgeEvidence.edge_id == entity_id)
    stmt = stmt.where(KnowledgeEvidence.is_active == True)  # noqa: E712
    return session.exec(stmt).one()


def update_digest_job(session: Session, job_id: int, **kwargs: object) -> None:
    """Compatibility shim after graph job table removal."""

    del session, job_id, kwargs
    return None
