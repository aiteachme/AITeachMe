"""Helpers for digest/curriculum build lifecycle maintenance."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

import structlog
from sqlmodel import Session, select

from app.models import (
    CurriculumVersion,
    KnowledgeEdge,
    KnowledgeNode,
    PrereqDagVersion,
    TeachingUnit,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitDependency,
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
    del session, job_id, job_type, progress, current_step


def cleanup_pending_by_job(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
    subject: str | None = None,
) -> int:
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
    total = 0
    if job_type == "graph":
        total += _cleanup_graph_pending_by_subject(session, subject=subject)
    else:
        total += _cleanup_curriculum_pending_by_subject(session, subject=subject)
    session.commit()
    logger.info("cleanup_pending_by_subject", subject=subject, job_type=job_type, deleted=total)
    return total


def _cleanup_graph_pending_by_subject(session: Session, *, subject: str) -> int:
    total = 0
    pending_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "pending",
            )
        ).all()
    )
    for row in pending_edges:
        session.delete(row)
    total += len(pending_edges)

    pending_nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == subject,
                KnowledgeNode.status == "pending",
            )
        ).all()
    )
    for row in pending_nodes:
        session.delete(row)
    total += len(pending_nodes)
    return total


def _cleanup_curriculum_pending_by_subject(session: Session, *, subject: str) -> int:
    total = 0

    draft_snapshots = list(
        session.exec(
            select(CurriculumVersion).where(
                CurriculumVersion.subject == subject,
                CurriculumVersion.status == "draft",
            )
        ).all()
    )
    for row in draft_snapshots:
        session.delete(row)
    total += len(draft_snapshots)

    draft_tree_versions = list(
        session.exec(
            select(ThemeTreeVersion).where(
                ThemeTreeVersion.subject == subject,
                ThemeTreeVersion.status == "draft",
            )
        ).all()
    )
    draft_tree_ids = {row.id for row in draft_tree_versions if row.id is not None}
    if draft_tree_ids:
        tree_nodes = list(
            session.exec(
                select(ThemeTreeNode).where(
                    ThemeTreeNode.tree_version_id.in_(draft_tree_ids)
                )
            ).all()
        )
        for row in tree_nodes:
            session.delete(row)
        total += len(tree_nodes)

    for row in draft_tree_versions:
        session.delete(row)
    total += len(draft_tree_versions)

    draft_dag_versions = list(
        session.exec(
            select(PrereqDagVersion).where(
                PrereqDagVersion.subject == subject,
                PrereqDagVersion.status == "draft",
            )
        ).all()
    )
    draft_dag_ids = {row.id for row in draft_dag_versions if row.id is not None}
    if draft_dag_ids:
        deps = list(
            session.exec(
                select(UnitDependency).where(
                    UnitDependency.dag_version_id.in_(draft_dag_ids)
                )
            ).all()
        )
        for row in deps:
            session.delete(row)
        total += len(deps)

    for row in draft_dag_versions:
        session.delete(row)
    total += len(draft_dag_versions)

    pending_units = list(
        session.exec(
            select(TeachingUnit).where(
                TeachingUnit.subject == subject,
                TeachingUnit.status == "pending",
            )
        ).all()
    )
    for row in pending_units:
        session.delete(row)
    total += len(pending_units)
    return total


def cleanup_orphan_pending_by_subject(
    session: Session,
    *,
    subject: str,
    ttl_hours: float = 1.0,
) -> int:
    cutoff = utcnow() - timedelta(hours=ttl_hours)
    total = 0

    stale_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "pending",
                KnowledgeEdge.created_at < cutoff,
            )
        ).all()
    )
    for row in stale_edges:
        session.delete(row)
    total += len(stale_edges)

    stale_nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == subject,
                KnowledgeNode.status == "pending",
                KnowledgeNode.created_at < cutoff,
            )
        ).all()
    )
    for row in stale_nodes:
        session.delete(row)
    total += len(stale_nodes)

    stale_units = list(
        session.exec(
            select(TeachingUnit).where(
                TeachingUnit.subject == subject,
                TeachingUnit.status == "pending",
                TeachingUnit.created_at < cutoff,
            )
        ).all()
    )
    for row in stale_units:
        session.delete(row)
    total += len(stale_units)

    session.commit()
    logger.info("cleanup_orphan_pending_by_subject", subject=subject, deleted=total)
    return total


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
    snapshot = session.get(CurriculumVersion, snapshot_id)
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
        for row in old_trees:
            row.status = "archived"
            session.add(row)

    if current_dag_version_id is not None:
        old_dags = session.exec(
            select(PrereqDagVersion).where(
                PrereqDagVersion.subject == subject,
                PrereqDagVersion.status == "published",
                PrereqDagVersion.id != current_dag_version_id,
            )
        ).all()
        for row in old_dags:
            row.status = "archived"
            session.add(row)

    if current_snapshot_id is not None:
        old_snapshots = session.exec(
            select(CurriculumVersion).where(
                CurriculumVersion.subject == subject,
                CurriculumVersion.status == "published",
                CurriculumVersion.id != current_snapshot_id,
            )
        ).all()
        for row in old_snapshots:
            row.status = "archived"
            session.add(row)


def activate_graph_entities_by_job(
    session: Session,
    *,
    job_id: int,
    subject: str | None = None,
) -> int:
    del job_id
    if not subject:
        return 0
    return activate_graph_entities_by_subject(session, subject=subject)


def activate_graph_entities_by_subject(session: Session, *, subject: str) -> int:
    total = 0

    nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == subject,
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
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "pending",
            )
        ).all()
    )
    for row in edges:
        row.status = "active"
        row.updated_at = utcnow()
        session.add(row)
    total += len(edges)

    session.commit()
    logger.info("activate_graph_entities_by_subject", subject=subject, activated=total)
    return total


def activate_curriculum_entities_by_job(
    session: Session,
    *,
    job_id: int,
    subject: str | None = None,
) -> int:
    del job_id
    if not subject:
        return 0
    return activate_curriculum_entities_by_subject(session, subject=subject)


def activate_curriculum_entities_by_subject(session: Session, *, subject: str) -> int:
    units = list(
        session.exec(
            select(TeachingUnit).where(
                TeachingUnit.subject == subject,
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
