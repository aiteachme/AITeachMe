"""Knowledge graph ingest job lifecycle helpers.

This module serves the `digest/kg_file_ingest` lane and the support-level
knowledge-graph build orchestration. It owns graph job progress updates,
pending entity cleanup, and pending-to-active promotion; generic utilities do
not belong here.
"""

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
    subject: str | None = None,
) -> None:
    from app.repositories.knowledge import knowledge_build_repo
    from app.shared.infra.knowledge.build_store import update_knowledge_build_status

    normalized_progress = max(0, min(int(progress), 100))
    safe_step = str(current_step or "").strip() or "running"
    stage_descriptions = {
        "acquire_lock": "正在获取图构建锁。",
        "prepare": "正在准备可构建的知识片段。",
        "extract": "正在抽取 KnowledgeUnit 候选。",
        "cluster": "正在聚类与合并候选 KnowledgeUnit。",
        "resolve_nodes": "正在解析并落库 KnowledgeUnit。",
        "resolve_edges": "正在解析并落库 KnowledgeEdge。",
        "analyze_impact": "正在分析图谱变更影响。",
        "finalize_graph": "正在完成图谱发布。",
    }

    resolved_subject = subject
    if resolved_subject:
        knowledge_build_repo.update_digest_job(
            session,
            job_id,
            subject=resolved_subject,
            status="processing",
            progress=normalized_progress,
            current_step=safe_step,
            job_type=job_type,
        )
        update_knowledge_build_status(
            resolved_subject,
            build_kind="graph",
            status="running",
            stage=safe_step,
            progress_pct=normalized_progress,
            current_stage_description=stage_descriptions.get(safe_step, "知识图谱构建进行中。"),
        )
        return

    knowledge_build_repo.update_digest_job(
        session,
        job_id,
        status="processing",
        progress=normalized_progress,
        current_step=safe_step,
        job_type=job_type,
    )


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


__all__ = [
    "activate_graph_entities_by_job",
    "activate_graph_entities_by_subject",
    "cleanup_orphan_pending_by_subject",
    "cleanup_pending_by_job",
    "cleanup_pending_by_subject",
    "stamp_graph_revision_by_subject",
    "update_job_progress",
]
