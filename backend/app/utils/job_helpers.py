"""Helpers for digest/curriculum build lifecycle maintenance."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import structlog
from sqlmodel import Session, select

from app.models.curriculum import (
    CurriculumDeriveJob,
    CurriculumSnapshot,
    PrereqDagVersion,
    TeachingUnit,
    TeachingUnitMembership,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitDependency,
    UnitTreeMembership,
)
from app.models.knowledge_graph import (
    EdgeRevision,
    EvidenceLink,
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeRevision,
)
from app.utils.time import utcnow

logger = structlog.get_logger()


def update_job_progress(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
    progress: int,
    current_step: str,
) -> None:
    """Compatibility shim after graph job table removal."""

    del session, job_id, job_type, progress, current_step


def cleanup_pending_by_job(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
) -> int:
    """Cleanup pending rows that were created by a specific job id."""

    total = 0
    if job_type == "graph":
        total += _delete_by_job(session, EvidenceLink, job_id)
        total += _delete_by_job(session, KnowledgeAlias, job_id)
        total += _delete_by_field(session, KnowledgeRevision, "digest_job_id", job_id)
        total += _delete_by_field(session, EdgeRevision, "digest_job_id", job_id)
        total += _delete_by_job(session, KnowledgeEdge, job_id, status_field="status", status_value="pending")
        total += _delete_by_job(session, KnowledgeNode, job_id, status_field="status", status_value="pending")
    else:
        total += _delete_by_job(session, UnitDependency, job_id)
        total += _delete_by_job(session, UnitTreeMembership, job_id)
        total += _delete_by_job(session, ThemeTreeNode, job_id)
        total += _delete_by_job_with_status(session, PrereqDagVersion, job_id, "draft")
        total += _delete_by_job_with_status(session, ThemeTreeVersion, job_id, "draft")
        total += _delete_by_job_with_status(session, CurriculumSnapshot, job_id, "draft")
        total += _delete_by_job(session, TeachingUnitMembership, job_id)
        total += _delete_by_job(session, TeachingUnit, job_id, status_field="status", status_value="pending")

    session.commit()
    logger.info("cleanup_pending_by_job", job_id=job_id, job_type=job_type, deleted=total)
    return total


def _delete_by_job(
    session: Session,
    model: type,
    job_id: int,
    *,
    status_field: str | None = None,
    status_value: str | None = None,
) -> int:
    stmt = select(model).where(model.created_by_job_id == job_id)  # type: ignore[attr-defined]
    if status_field and status_value:
        stmt = stmt.where(getattr(model, status_field) == status_value)
    rows = session.exec(stmt).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def _delete_by_field(session: Session, model: type, field_name: str, job_id: int) -> int:
    stmt = select(model).where(getattr(model, field_name) == job_id)
    rows = session.exec(stmt).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def _delete_by_job_with_status(
    session: Session,
    model: type,
    job_id: int,
    status_value: str,
) -> int:
    stmt = select(model).where(
        model.created_by_job_id == job_id,  # type: ignore[attr-defined]
        model.status == status_value,  # type: ignore[attr-defined]
    )
    rows = session.exec(stmt).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def cleanup_orphan_pending_by_subject(
    session: Session,
    *,
    subject: str,
    ttl_hours: float = 1.0,
) -> int:
    """Cleanup stale pending rows that are no longer part of active processing jobs."""

    cutoff = utcnow() - timedelta(hours=ttl_hours)

    processing_graph_ids: set[int] = set()
    processing_curriculum_ids = {
        j.id
        for j in session.exec(
            select(CurriculumDeriveJob).where(
                CurriculumDeriveJob.subject == subject,
                CurriculumDeriveJob.status == "processing",
            )
        ).all()
    }

    total = 0
    total += _delete_orphan_pending(session, KnowledgeNode, subject, cutoff, processing_graph_ids)
    total += _delete_orphan_pending(session, KnowledgeEdge, subject, cutoff, processing_graph_ids)
    total += _delete_orphan_pending(
        session,
        KnowledgeAlias,
        subject,
        cutoff,
        processing_graph_ids,
        subject_via_node=True,
    )
    total += _delete_orphan_pending(session, EvidenceLink, subject, cutoff, processing_graph_ids)
    total += _delete_orphan_pending(session, TeachingUnit, subject, cutoff, processing_curriculum_ids)
    total += _delete_orphan_pending(
        session,
        TeachingUnitMembership,
        subject,
        cutoff,
        processing_curriculum_ids,
        subject_via_unit=True,
    )
    session.commit()
    logger.info("cleanup_orphan_pending_by_subject", subject=subject, deleted=total)
    return total


def _delete_orphan_pending(
    session: Session,
    model: type,
    subject: str,
    cutoff: datetime,
    exclude_job_ids: set[int],
    *,
    subject_via_node: bool = False,
    subject_via_unit: bool = False,
) -> int:
    if subject_via_node or subject_via_unit:
        stmt = select(model).where(model.created_at < cutoff)  # type: ignore[attr-defined]
    else:
        stmt = select(model).where(
            model.subject == subject,  # type: ignore[attr-defined]
            model.created_at < cutoff,  # type: ignore[attr-defined]
        )

    if hasattr(model, "status"):
        stmt = stmt.where(model.status.in_(["pending", "draft"]))  # type: ignore[attr-defined]

    rows = session.exec(stmt).all()
    count = 0
    for row in rows:
        job_id = getattr(row, "created_by_job_id", None)
        if job_id in exclude_job_ids:
            continue
        session.delete(row)
        count += 1
    return count


def publish_theme_tree_version(session: Session, *, version_id: int) -> None:
    version = session.get(ThemeTreeVersion, version_id)
    if version is None:
        return
    version.status = "published"
    session.add(version)


def publish_prereq_dag_version(session: Session, *, version_id: int) -> None:
    version = session.get(PrereqDagVersion, version_id)
    if version is None:
        return
    version.status = "published"
    session.add(version)


def publish_curriculum_snapshot(session: Session, *, snapshot_id: int) -> None:
    snapshot = session.get(CurriculumSnapshot, snapshot_id)
    if snapshot is None:
        return
    snapshot.status = "published"
    session.add(snapshot)


def archive_old_versions(
    session: Session,
    *,
    subject: str,
    current_tree_version_id: int | None = None,
    current_dag_version_id: int | None = None,
    current_snapshot_id: int | None = None,
) -> None:
    if current_tree_version_id is not None:
        old_trees = session.exec(
            select(ThemeTreeVersion).where(
                ThemeTreeVersion.subject == subject,
                ThemeTreeVersion.status == "published",
                ThemeTreeVersion.id != current_tree_version_id,
            )
        ).all()
        for v in old_trees:
            v.status = "archived"
            session.add(v)

    if current_dag_version_id is not None:
        old_dags = session.exec(
            select(PrereqDagVersion).where(
                PrereqDagVersion.subject == subject,
                PrereqDagVersion.status == "published",
                PrereqDagVersion.id != current_dag_version_id,
            )
        ).all()
        for v in old_dags:
            v.status = "archived"
            session.add(v)

    if current_snapshot_id is not None:
        old_snapshots = session.exec(
            select(CurriculumSnapshot).where(
                CurriculumSnapshot.subject == subject,
                CurriculumSnapshot.status == "published",
                CurriculumSnapshot.id != current_snapshot_id,
            )
        ).all()
        for s in old_snapshots:
            s.status = "archived"
            session.add(s)


def activate_graph_entities_by_job(session: Session, *, job_id: int) -> int:
    total = 0
    total += _activate_entities(session, KnowledgeNode, job_id)
    total += _activate_entities(session, KnowledgeEdge, job_id)
    total += _activate_aliases_by_job(session, job_id)
    total += _activate_evidence_by_job(session, job_id)
    session.commit()
    logger.info("activate_graph_entities_by_job", job_id=job_id, activated=total)
    return total


def activate_curriculum_entities_by_job(session: Session, *, job_id: int) -> int:
    total = 0
    total += _activate_entities(session, TeachingUnit, job_id)
    session.commit()
    logger.info("activate_curriculum_entities_by_job", job_id=job_id, activated=total)
    return total


def _activate_entities(session: Session, model: type, job_id: int) -> int:
    stmt = select(model).where(
        model.created_by_job_id == job_id,  # type: ignore[attr-defined]
        model.status == "pending",  # type: ignore[attr-defined]
    )
    rows = session.exec(stmt).all()
    for row in rows:
        row.status = "active"
        if hasattr(row, "updated_at"):
            row.updated_at = utcnow()
        session.add(row)
    return len(rows)


def _activate_aliases_by_job(session: Session, job_id: int) -> int:
    stmt = select(KnowledgeAlias).where(KnowledgeAlias.created_by_job_id == job_id)
    rows = session.exec(stmt).all()
    count = 0
    for row in rows:
        if row.status != "active":
            row.status = "active"
            session.add(row)
            count += 1
    return count


def _activate_evidence_by_job(session: Session, job_id: int) -> int:
    stmt = select(EvidenceLink).where(
        EvidenceLink.created_by_job_id == job_id,
        EvidenceLink.is_active == False,  # noqa: E712
    )
    rows = session.exec(stmt).all()
    for row in rows:
        row.is_active = True
        session.add(row)
    return len(rows)
