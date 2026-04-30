"""Docs-sync graph persistence node."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.shared.infra.database import managed_session
from app.shared.infra.workflow.live_stream import publish_workflow_stream_event
from app.utils.time import utcnow
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import persist_knowledge_graph_items
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncReport
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def _report_metrics(report: KnowledgeSyncReport, *, elapsed_ms: int) -> dict[str, object]:
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "sync_run_id": report.sync_run_id,
        "doc_version_no": report.doc_version_no,
        "chapter_count": report.chapter_count,
        "section_count": report.section_count,
        "chapter_split_count": report.chapter_split_count,
        "chapter_task_count": report.chapter_task_count,
        "subsection_task_count": report.subsection_task_count,
        "successful_section_count": report.successful_section_count,
        "failed_section_count": report.failed_section_count,
        "unit_change_count": report.unit_change_count,
        "edge_change_count": report.edge_change_count,
        "created_unit_count": len(report.created_unit_ids),
        "updated_unit_count": len(report.updated_unit_ids),
        "deprecated_unit_count": report.deprecated_unit_count,
        "created_edge_count": len(report.created_edge_ids),
        "updated_edge_count": len(report.updated_edge_ids),
        "deprecated_edge_count": report.deprecated_edge_count,
        "llm_error_count": report.llm_error_count,
        "empty_llm_result_count": report.empty_llm_result_count,
        "empty_repair_attempt_count": report.empty_repair_attempt_count,
        "empty_repair_success_count": report.empty_repair_success_count,
        "source_ref_count": report.source_ref_count,
        "backbone_unit_count": report.backbone_unit_count,
        "backbone_edge_count": report.backbone_edge_count,
        "stitched_edge_count": report.stitched_edge_count,
        "section_local_stitch_edge_count": report.section_local_stitch_edge_count,
        "mention_stitch_edge_count": report.mention_stitch_edge_count,
        "graph_isolated_unit_count": report.graph_isolated_unit_count,
        "graph_component_count": report.graph_component_count,
        "graph_largest_component_unit_count": report.graph_largest_component_unit_count,
        "graph_active_unit_count": report.graph_active_unit_count,
        "graph_active_edge_count": report.graph_active_edge_count,
        "graph_avg_degree": report.graph_avg_degree,
        "graph_isolated_unit_pct": report.graph_isolated_unit_pct,
        "stable_anchor_count": report.stable_anchor_count,
    }


def persist_node(state: DocsSyncState) -> DocsSyncState:
    """Persist successful extraction payloads into graph tables and sync metrics."""

    started_at = perf_counter()
    run_context = state.get("sync_run_context")
    payload = state.get("extraction_payload")
    if run_context is None:
        return with_node_error(state, "persist", "docs_sync_run_context_missing")
    if payload is None:
        return with_node_error(state, "persist", "docs_sync_extraction_payload_missing")

    try:
        with managed_session() as session:
            report = persist_knowledge_graph_items(
                session,
                run_context=run_context,
                payload=payload,
            )
        publish_workflow_stream_event(
            run_context.course_id,
            "graph_delta",
            {
                "stage": "persist",
                "build_revision_no": run_context.build_revision_no,
                "unit_count": report.unit_change_count,
                "edge_count": report.edge_change_count,
                "created_unit_count": len(report.created_unit_ids),
                "updated_unit_count": len(report.updated_unit_ids),
                "deprecated_unit_count": report.deprecated_unit_count,
                "created_edge_count": len(report.created_edge_ids),
                "updated_edge_count": len(report.updated_edge_ids),
                "deprecated_edge_count": report.deprecated_edge_count,
                "graph_active_unit_count": report.graph_active_unit_count,
                "graph_active_edge_count": report.graph_active_edge_count,
                "emitted_at": utcnow().isoformat(),
            },
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        return with_node_metrics(
            state,
            "persist",
            _report_metrics(report, elapsed_ms=elapsed_ms),
            report=report,
            error=None,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_persist_failed",
            course_id=state.get("course_id"),
            build_session_id=state.get("build_session_id"),
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_error(
            state,
            "persist",
            str(exc),
            metrics={"elapsed_ms": elapsed_ms},
            report=None,
        )


__all__ = ["persist_node"]
