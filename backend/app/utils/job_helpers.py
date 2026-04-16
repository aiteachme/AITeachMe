"""Helpers for digest graph build lifecycle maintenance."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

import structlog
from sqlmodel import Session, select

from app.models import KnowledgeEdge, KnowledgeUnit
from app.utils.time import utcnow

logger = structlog.get_logger()


def update_job_progress(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph"],
    progress: int,
    current_step: str,
) -> None:
    del session, job_id, job_type, progress, current_step


def cleanup_pending_by_job(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph"],
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
    job_type: Literal["graph"],
) -> int:
    total = _cleanup_graph_pending_by_subject(session, subject=subject)
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
            select(KnowledgeUnit).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status == "pending",
            )
        ).all()
    )
    for row in pending_nodes:
        session.delete(row)
    total += len(pending_nodes)
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
            select(KnowledgeUnit).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status == "pending",
                KnowledgeUnit.created_at < cutoff,
            )
        ).all()
    )
    for row in stale_nodes:
        session.delete(row)
    total += len(stale_nodes)

    session.commit()
    logger.info("cleanup_orphan_pending_by_subject", subject=subject, deleted=total)
    return total


def stamp_graph_revision_by_subject(
    session: Session,
    *,
    subject: str,
    version_no: int,
) -> int:
    total = 0
    nodes = list(
        session.exec(
            select(KnowledgeUnit).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status == "active",
            )
        ).all()
    )
    for row in nodes:
        row.build_revision_no = version_no
        row.updated_at = utcnow()
        session.add(row)
    total += len(nodes)

    edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "active",
            )
        ).all()
    )
    for row in edges:
        row.build_revision_no = version_no
        row.updated_at = utcnow()
        session.add(row)
    total += len(edges)
    return total


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
            select(KnowledgeUnit).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status == "pending",
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

