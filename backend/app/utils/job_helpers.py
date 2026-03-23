"""Helpers for digest/curriculum build lifecycle maintenance."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

import structlog
from sqlmodel import Session, select

from app.models.curriculum import (
    CurriculumSnapshot,
    PrereqDagVersion,
    TeachingUnit,
    TeachingUnitMembership,
    TeachingUnitRevision,
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
    """Compatibility shim after job-table removal."""

    del session, job_id, job_type, progress, current_step


def cleanup_pending_by_job(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
    subject: str | None = None,
) -> int:
    """Backward-compatible API: cleanup now scopes by subject+status, not by job id."""

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

    pending_nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == subject,
                KnowledgeNode.status == "pending",
            )
        ).all()
    )
    pending_node_ids = {row.id for row in pending_nodes if row.id is not None}

    pending_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "pending",
            )
        ).all()
    )
    pending_edge_ids = {row.id for row in pending_edges if row.id is not None}

    if pending_node_ids:
        node_aliases = list(
            session.exec(
                select(KnowledgeAlias).where(
                    KnowledgeAlias.node_id.in_(pending_node_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in node_aliases:
            session.delete(row)
        total += len(node_aliases)

        node_revisions = list(
            session.exec(
                select(KnowledgeRevision).where(
                    KnowledgeRevision.node_id.in_(pending_node_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in node_revisions:
            session.delete(row)
        total += len(node_revisions)

        node_evidence = list(
            session.exec(
                select(EvidenceLink).where(
                    EvidenceLink.subject == subject,
                    EvidenceLink.entity_type == "node",
                    EvidenceLink.entity_id.in_(pending_node_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in node_evidence:
            session.delete(row)
        total += len(node_evidence)

    if pending_edge_ids:
        edge_revisions = list(
            session.exec(
                select(EdgeRevision).where(
                    EdgeRevision.edge_id.in_(pending_edge_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in edge_revisions:
            session.delete(row)
        total += len(edge_revisions)

        edge_evidence = list(
            session.exec(
                select(EvidenceLink).where(
                    EvidenceLink.subject == subject,
                    EvidenceLink.entity_type == "edge",
                    EvidenceLink.entity_id.in_(pending_edge_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in edge_evidence:
            session.delete(row)
        total += len(edge_evidence)

    for row in pending_edges:
        session.delete(row)
    total += len(pending_edges)

    for row in pending_nodes:
        session.delete(row)
    total += len(pending_nodes)

    return total


def _cleanup_curriculum_pending_by_subject(session: Session, *, subject: str) -> int:
    total = 0

    draft_snapshots = list(
        session.exec(
            select(CurriculumSnapshot).where(
                CurriculumSnapshot.subject == subject,
                CurriculumSnapshot.status == "draft",
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
        tree_memberships = list(
            session.exec(
                select(UnitTreeMembership).where(
                    UnitTreeMembership.tree_version_id.in_(draft_tree_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in tree_memberships:
            session.delete(row)
        total += len(tree_memberships)

        tree_nodes = list(
            session.exec(
                select(ThemeTreeNode).where(
                    ThemeTreeNode.tree_version_id.in_(draft_tree_ids),  # type: ignore[union-attr]
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
                    UnitDependency.dag_version_id.in_(draft_dag_ids),  # type: ignore[union-attr]
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
    pending_unit_ids = {row.id for row in pending_units if row.id is not None}
    if pending_unit_ids:
        revisions = list(
            session.exec(
                select(TeachingUnitRevision).where(
                    TeachingUnitRevision.unit_id.in_(pending_unit_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in revisions:
            session.delete(row)
        total += len(revisions)

        memberships = list(
            session.exec(
                select(TeachingUnitMembership).where(
                    TeachingUnitMembership.unit_id.in_(pending_unit_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in memberships:
            session.delete(row)
        total += len(memberships)

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
    """Cleanup stale pending/draft rows by subject age."""

    cutoff = utcnow() - timedelta(hours=ttl_hours)
    total = 0

    stale_nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == subject,
                KnowledgeNode.status == "pending",
                KnowledgeNode.created_at < cutoff,
            )
        ).all()
    )
    stale_node_ids = {row.id for row in stale_nodes if row.id is not None}

    if stale_node_ids:
        stale_aliases = list(
            session.exec(
                select(KnowledgeAlias).where(
                    KnowledgeAlias.node_id.in_(stale_node_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in stale_aliases:
            session.delete(row)
        total += len(stale_aliases)

        stale_node_revisions = list(
            session.exec(
                select(KnowledgeRevision).where(
                    KnowledgeRevision.node_id.in_(stale_node_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in stale_node_revisions:
            session.delete(row)
        total += len(stale_node_revisions)

        stale_node_evidence = list(
            session.exec(
                select(EvidenceLink).where(
                    EvidenceLink.subject == subject,
                    EvidenceLink.entity_type == "node",
                    EvidenceLink.entity_id.in_(stale_node_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in stale_node_evidence:
            session.delete(row)
        total += len(stale_node_evidence)

    stale_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "pending",
                KnowledgeEdge.created_at < cutoff,
            )
        ).all()
    )
    stale_edge_ids = {row.id for row in stale_edges if row.id is not None}
    if stale_edge_ids:
        stale_edge_revisions = list(
            session.exec(
                select(EdgeRevision).where(
                    EdgeRevision.edge_id.in_(stale_edge_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in stale_edge_revisions:
            session.delete(row)
        total += len(stale_edge_revisions)

        stale_edge_evidence = list(
            session.exec(
                select(EvidenceLink).where(
                    EvidenceLink.subject == subject,
                    EvidenceLink.entity_type == "edge",
                    EvidenceLink.entity_id.in_(stale_edge_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in stale_edge_evidence:
            session.delete(row)
        total += len(stale_edge_evidence)

    for row in stale_edges:
        session.delete(row)
    total += len(stale_edges)

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
    stale_unit_ids = {row.id for row in stale_units if row.id is not None}
    for row in stale_units:
        session.delete(row)
    total += len(stale_units)

    if stale_unit_ids:
        stale_memberships = list(
            session.exec(
                select(TeachingUnitMembership).where(
                    TeachingUnitMembership.unit_id.in_(stale_unit_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        for row in stale_memberships:
            session.delete(row)
        total += len(stale_memberships)

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
            select(CurriculumSnapshot).where(
                CurriculumSnapshot.subject == subject,
                CurriculumSnapshot.status == "published",
                CurriculumSnapshot.id != current_snapshot_id,
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
    """Backward-compatible API: activation now scopes by subject."""

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

    aliases = list(
        session.exec(
            select(KnowledgeAlias)
            .join(KnowledgeNode, KnowledgeAlias.node_id == KnowledgeNode.id)
            .where(
                KnowledgeNode.subject == subject,
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
            select(EvidenceLink).where(
                EvidenceLink.subject == subject,
                EvidenceLink.is_active == False,  # noqa: E712
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
    """Backward-compatible API: activation now scopes by subject."""

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
