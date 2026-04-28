"""Persistence helpers for knowledge-graph sync-run rows."""

from __future__ import annotations

import json

import structlog
from sqlmodel import Session

from app.models.knowledge_graph_sync import KnowledgeGraphSyncRun
from app.utils.time import utcnow
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncReport

logger = structlog.get_logger()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def create_sync_run(
    session: Session,
    *,
    subject_id: str,
    build_session_id: str | None,
    doc_version_no: int,
    graph_revision_no: int,
) -> KnowledgeGraphSyncRun:
    now = utcnow()
    sync_run = KnowledgeGraphSyncRun(
        subject_id=subject_id,
        build_session_id=(build_session_id or None),
        doc_version_no=doc_version_no,
        graph_revision_no=graph_revision_no,
        status="running",
        started_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(sync_run)
    session.flush()
    return sync_run


def get_sync_run_or_raise(session: Session, sync_run_id: int | None) -> KnowledgeGraphSyncRun:
    if not sync_run_id:
        raise RuntimeError("knowledge_graph_sync_run_id_missing")
    sync_run = session.get(KnowledgeGraphSyncRun, sync_run_id)
    if sync_run is None:
        raise RuntimeError(f"knowledge_graph_sync_run_not_found:{sync_run_id}")
    return sync_run


def sync_run_metrics(report: KnowledgeSyncReport) -> dict[str, int]:
    return {
        "chapter_count": report.chapter_count,
        "section_count": report.section_count,
        "chapter_split_count": report.chapter_split_count,
        "chapter_task_count": report.chapter_task_count,
        "subsection_task_count": report.subsection_task_count,
        "successful_section_count": report.successful_section_count,
        "failed_section_count": report.failed_section_count,
        "llm_section_count": report.llm_section_count,
        "llm_error_count": report.llm_error_count,
        "empty_llm_result_count": report.empty_llm_result_count,
        "empty_repair_attempt_count": report.empty_repair_attempt_count,
        "empty_repair_success_count": report.empty_repair_success_count,
        "unit_change_count": report.unit_change_count,
        "edge_change_count": report.edge_change_count,
        "deprecated_unit_count": report.deprecated_unit_count,
        "deprecated_edge_count": report.deprecated_edge_count,
        "source_ref_count": report.source_ref_count,
        "backbone_unit_count": report.backbone_unit_count,
        "backbone_edge_count": report.backbone_edge_count,
        "stable_anchor_count": report.stable_anchor_count,
        "elapsed_ms": report.elapsed_ms,
    }


def finish_sync_run(
    session: Session,
    sync_run: KnowledgeGraphSyncRun,
    *,
    status: str,
    metrics: dict[str, int],
    error_message: str = "",
) -> None:
    sync_run.status = status
    sync_run.metrics_json = _json_dumps(metrics)
    sync_run.error_message = error_message
    sync_run.finished_at = utcnow()
    sync_run.updated_at = sync_run.finished_at
    session.add(sync_run)


def mark_knowledge_graph_sync_run_failed(
    session: Session,
    *,
    sync_run_id: int | None,
    error_message: str,
    metrics: dict[str, int] | None = None,
) -> None:
    """Best-effort failure marker used by split graph nodes."""

    try:
        sync_run = get_sync_run_or_raise(session, sync_run_id)
    except Exception:
        logger.warning(
            "knowledge_docs_sync_fail_marker_skipped",
            sync_run_id=sync_run_id,
            error=error_message,
        )
        return
    finish_sync_run(
        session,
        sync_run,
        status="failed",
        metrics=metrics or {},
        error_message=error_message,
    )


__all__ = [
    "create_sync_run",
    "finish_sync_run",
    "get_sync_run_or_raise",
    "mark_knowledge_graph_sync_run_failed",
    "sync_run_metrics",
]
