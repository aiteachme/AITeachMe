"""Helpers for digest and curriculum lifecycle maintenance on the new schema."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

import structlog
from sqlmodel import Session, select

from app.models import (
    CurriculumDependency,
    CurriculumTreeNode,
    CurriculumUnitLink,
    CurriculumVersion,
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeEvidence,
    KnowledgeNode,
    Subject,
    TeachingUnit,
    TeachingUnitMembership,
)
from app.utils.time import utcnow

logger = structlog.get_logger()


def _get_subject_id(session: Session, subject: str) -> int | None:
    subject_row = session.exec(select(Subject).where(Subject.slug == subject)).first()
    if subject_row is None or subject_row.id is None:
        return None
    return int(subject_row.id)


def _delete_rows(session: Session, rows: list[object]) -> int:
    for row in rows:
        session.delete(row)
    return len(rows)


def update_job_progress(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
    progress: int,
    current_step: str,
) -> None:
    """Compatibility shim after job-table removal."""

    del session, job_id, job_type, progress, current_step


def cleanup_pending_by_job(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
    subject: str | None = None,
) -> int:
    """Compatibility shim that now scopes cleanup by subject."""

    del job_id
    if not subject:
        return 0
    return cleanup_pending_by_subject(session, subject=subject, job_type=job_type)


def cleanup_pending_by_subject(
    session: Session,
    *,
    subject: str,
    job_type: Literal["graph", "curriculum"],
) -> int:
    """Delete pending graph rows or draft curriculum rows for one subject."""

    subject_id = _get_subject_id(session, subject)
    if subject_id is None:
        return 0

    total = (
        _cleanup_graph_pending_by_subject(session, subject_id=subject_id)
        if job_type == "graph"
        else _cleanup_curriculum_pending_by_subject(session, subject_id=subject_id)
    )
    session.commit()
    logger.info("cleanup_pending_by_subject", subject=subject, job_type=job_type, deleted=total)
    return total


def _cleanup_graph_pending_by_subject(session: Session, *, subject_id: int) -> int:
    total = 0

    pending_nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject_id == subject_id,
                KnowledgeNode.status == "pending",
            )
        ).all()
    )
    pending_node_ids = [int(row.id) for row in pending_nodes if row.id is not None]

    pending_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject_id == subject_id,
                KnowledgeEdge.status == "pending",
            )
        ).all()
    )
    pending_edge_ids = [int(row.id) for row in pending_edges if row.id is not None]

    if pending_node_ids:
        aliases = list(
            session.exec(
                select(KnowledgeAlias).where(KnowledgeAlias.node_id.in_(pending_node_ids))  # type: ignore[union-attr]
            ).all()
        )
        total += _delete_rows(session, aliases)

    if pending_node_ids or pending_edge_ids:
        evidence_stmt = select(KnowledgeEvidence).where(KnowledgeEvidence.subject_id == subject_id)
        evidence_rows = list(session.exec(evidence_stmt).all())
        evidence_to_delete = [
            row
            for row in evidence_rows
            if (row.node_id is not None and row.node_id in pending_node_ids)
            or (row.edge_id is not None and row.edge_id in pending_edge_ids)
        ]
        total += _delete_rows(session, evidence_to_delete)

    total += _delete_rows(session, pending_edges)
    total += _delete_rows(session, pending_nodes)
    return total


def _cleanup_curriculum_pending_by_subject(session: Session, *, subject_id: int) -> int:
    total = 0

    pending_units = list(
        session.exec(
            select(TeachingUnit).where(
                TeachingUnit.subject_id == subject_id,
                TeachingUnit.status == "pending",
            )
        ).all()
    )
    pending_unit_ids = [int(row.id) for row in pending_units if row.id is not None]
    if pending_unit_ids:
        memberships = list(
            session.exec(
                select(TeachingUnitMembership).where(
                    TeachingUnitMembership.unit_id.in_(pending_unit_ids)  # type: ignore[union-attr]
                )
            ).all()
        )
        total += _delete_rows(session, memberships)
    total += _delete_rows(session, pending_units)

    draft_versions = list(
        session.exec(
            select(CurriculumVersion).where(
                CurriculumVersion.subject_id == subject_id,
                CurriculumVersion.status == "draft",
            )
        ).all()
    )
    draft_version_ids = [int(row.id) for row in draft_versions if row.id is not None]
    if draft_version_ids:
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(CurriculumUnitLink).where(
                        CurriculumUnitLink.curriculum_version_id.in_(draft_version_ids)  # type: ignore[union-attr]
                    )
                ).all()
            ),
        )
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(CurriculumDependency).where(
                        CurriculumDependency.curriculum_version_id.in_(draft_version_ids)  # type: ignore[union-attr]
                    )
                ).all()
            ),
        )
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(CurriculumTreeNode).where(
                        CurriculumTreeNode.curriculum_version_id.in_(draft_version_ids)  # type: ignore[union-attr]
                    )
                ).all()
            ),
        )
    total += _delete_rows(session, draft_versions)
    return total


def cleanup_orphan_pending_by_subject(
    session: Session,
    *,
    subject: str,
    ttl_hours: float = 1.0,
) -> int:
    """Delete stale pending rows that were left behind by interrupted builds."""

    subject_id = _get_subject_id(session, subject)
    if subject_id is None:
        return 0

    cutoff = utcnow() - timedelta(hours=ttl_hours)
    total = 0

    stale_nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject_id == subject_id,
                KnowledgeNode.status == "pending",
                KnowledgeNode.created_at < cutoff,
            )
        ).all()
    )
    stale_node_ids = [int(row.id) for row in stale_nodes if row.id is not None]
    if stale_node_ids:
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(KnowledgeAlias).where(KnowledgeAlias.node_id.in_(stale_node_ids))  # type: ignore[union-attr]
                ).all()
            ),
        )

    stale_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject_id == subject_id,
                KnowledgeEdge.status == "pending",
                KnowledgeEdge.created_at < cutoff,
            )
        ).all()
    )
    stale_edge_ids = [int(row.id) for row in stale_edges if row.id is not None]

    if stale_node_ids or stale_edge_ids:
        evidence_rows = list(session.exec(select(KnowledgeEvidence).where(KnowledgeEvidence.subject_id == subject_id)).all())
        evidence_to_delete = [
            row
            for row in evidence_rows
            if (row.node_id is not None and row.node_id in stale_node_ids)
            or (row.edge_id is not None and row.edge_id in stale_edge_ids)
        ]
        total += _delete_rows(session, evidence_to_delete)

    stale_units = list(
        session.exec(
            select(TeachingUnit).where(
                TeachingUnit.subject_id == subject_id,
                TeachingUnit.status == "pending",
                TeachingUnit.created_at < cutoff,
            )
        ).all()
    )
    stale_unit_ids = [int(row.id) for row in stale_units if row.id is not None]
    if stale_unit_ids:
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(TeachingUnitMembership).where(
                        TeachingUnitMembership.unit_id.in_(stale_unit_ids)  # type: ignore[union-attr]
                    )
                ).all()
            ),
        )

    stale_versions = list(
        session.exec(
            select(CurriculumVersion).where(
                CurriculumVersion.subject_id == subject_id,
                CurriculumVersion.status == "draft",
                CurriculumVersion.created_at < cutoff,
            )
        ).all()
    )
    stale_version_ids = [int(row.id) for row in stale_versions if row.id is not None]
    if stale_version_ids:
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(CurriculumUnitLink).where(
                        CurriculumUnitLink.curriculum_version_id.in_(stale_version_ids)  # type: ignore[union-attr]
                    )
                ).all()
            ),
        )
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(CurriculumDependency).where(
                        CurriculumDependency.curriculum_version_id.in_(stale_version_ids)  # type: ignore[union-attr]
                    )
                ).all()
            ),
        )
        total += _delete_rows(
            session,
            list(
                session.exec(
                    select(CurriculumTreeNode).where(
                        CurriculumTreeNode.curriculum_version_id.in_(stale_version_ids)  # type: ignore[union-attr]
                    )
                ).all()
            ),
        )

    total += _delete_rows(session, stale_edges)
    total += _delete_rows(session, stale_nodes)
    total += _delete_rows(session, stale_units)
    total += _delete_rows(session, stale_versions)

    session.commit()
    logger.info("cleanup_orphan_pending_by_subject", subject=subject, deleted=total)
    return total


def _publish_curriculum_version(session: Session, *, version_id: int) -> None:
    version = session.get(CurriculumVersion, version_id)
    if version is None:
        return
    version.status = "published"
    version.published_at = utcnow()
    version.updated_at = utcnow()
    session.add(version)


def publish_theme_tree_version(session: Session, *, version_id: int) -> None:
    _publish_curriculum_version(session, version_id=version_id)


def publish_prereq_dag_version(session: Session, *, version_id: int) -> None:
    _publish_curriculum_version(session, version_id=version_id)


def publish_curriculum_snapshot(session: Session, *, snapshot_id: int) -> None:
    _publish_curriculum_version(session, version_id=snapshot_id)


def archive_old_versions(
    session: Session,
    *,
    subject: str,
    current_tree_version_id: int | None = None,
    current_dag_version_id: int | None = None,
    current_snapshot_id: int | None = None,
) -> None:
    """Archive older published curriculum versions for one subject."""

    subject_id = _get_subject_id(session, subject)
    if subject_id is None:
        return

    keep_version_id = current_snapshot_id or current_tree_version_id or current_dag_version_id
    if keep_version_id is None:
        return

    old_versions = list(
        session.exec(
            select(CurriculumVersion).where(
                CurriculumVersion.subject_id == subject_id,
                CurriculumVersion.status == "published",
                CurriculumVersion.id != keep_version_id,
            )
        ).all()
    )
    for row in old_versions:
        row.status = "archived"
        row.updated_at = utcnow()
        session.add(row)


def activate_graph_entities_by_job(
    session: Session,
    *,
    job_id: int,
    subject: str | None = None,
) -> int:
    """Compatibility shim that now scopes activation by subject."""

    del job_id
    if not subject:
        return 0
    return activate_graph_entities_by_subject(session, subject=subject)


def activate_graph_entities_by_subject(session: Session, *, subject: str) -> int:
    """Flip pending graph rows to active for one subject."""

    subject_id = _get_subject_id(session, subject)
    if subject_id is None:
        return 0

    total = 0
    nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject_id == subject_id,
                KnowledgeNode.status == "pending",
            )
        ).all()
    )
    for row in nodes:
        row.status = "active"
        row.updated_at = utcnow()
        session.add(row)
    total += len(nodes)

    edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject_id == subject_id,
                KnowledgeEdge.status == "pending",
            )
        ).all()
    )
    for row in edges:
        row.status = "active"
        row.updated_at = utcnow()
        session.add(row)
    total += len(edges)

    aliases = list(
        session.exec(
            select(KnowledgeAlias)
            .join(KnowledgeNode, KnowledgeAlias.node_id == KnowledgeNode.id)
            .where(
                KnowledgeNode.subject_id == subject_id,
                KnowledgeAlias.status != "active",
            )
        ).all()
    )
    for row in aliases:
        row.status = "active"
        session.add(row)
    total += len(aliases)

    evidence = list(
        session.exec(
            select(KnowledgeEvidence).where(
                KnowledgeEvidence.subject_id == subject_id,
                KnowledgeEvidence.is_active == False,  # noqa: E712
            )
        ).all()
    )
    for row in evidence:
        row.is_active = True
        session.add(row)
    total += len(evidence)

    session.commit()
    logger.info("activate_graph_entities_by_subject", subject=subject, activated=total)
    return total


def activate_curriculum_entities_by_job(
    session: Session,
    *,
    job_id: int,
    subject: str | None = None,
) -> int:
    """Compatibility shim that now scopes activation by subject."""

    del job_id
    if not subject:
        return 0
    return activate_curriculum_entities_by_subject(session, subject=subject)


def activate_curriculum_entities_by_subject(session: Session, *, subject: str) -> int:
    """Flip pending teaching units to active for one subject."""

    subject_id = _get_subject_id(session, subject)
    if subject_id is None:
        return 0

    units = list(
        session.exec(
            select(TeachingUnit).where(
                TeachingUnit.subject_id == subject_id,
                TeachingUnit.status == "pending",
            )
        ).all()
    )
    for row in units:
        row.status = "active"
        row.updated_at = utcnow()
        session.add(row)
    session.commit()
    logger.info("activate_curriculum_entities_by_subject", subject=subject, activated=len(units))
    return len(units)
