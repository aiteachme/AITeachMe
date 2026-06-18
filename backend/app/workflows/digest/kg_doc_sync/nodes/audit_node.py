"""Docs-sync graph quality audit node."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncExtractionPayload
from app.workflows.digest.kg_doc_sync.lib.quality import audit_knowledge_sync_payload
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def _audit_metrics(payload: KnowledgeSyncExtractionPayload, *, elapsed_ms: int) -> dict[str, object]:
    diagnostics = dict(payload.diagnostics_totals or {})
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "unit_count": len(payload.units),
        "edge_count": len(payload.extracted_edges),
        "downstream_unit_count": int(diagnostics.get("graph_audit_downstream_unit_count", 0) or 0),
        "exam_ready_unit_count": int(diagnostics.get("graph_audit_exam_ready_unit_count", 0) or 0),
        "profile_ready_unit_count": int(diagnostics.get("graph_audit_profile_ready_unit_count", 0) or 0),
        "diagnostic_unit_count": int(diagnostics.get("graph_audit_diagnostic_unit_count", 0) or 0),
        "valid_relation_edge_count": int(diagnostics.get("graph_audit_valid_relation_edge_count", 0) or 0),
        "structure_edge_count": int(diagnostics.get("graph_audit_structure_edge_count", 0) or 0),
        "exam_edge_count": int(diagnostics.get("graph_audit_exam_edge_count", 0) or 0),
        "examine_profile_ready": int(diagnostics.get("graph_audit_examine_profile_ready", 0) or 0),
        "missing_chapter_count": int(diagnostics.get("graph_audit_missing_chapter_count", 0) or 0),
        "chapter_coverage_pct": float(diagnostics.get("graph_audit_chapter_coverage_pct", 0.0) or 0.0),
        "nonstandard_unit_type_count": int(diagnostics.get("graph_audit_nonstandard_unit_type_count", 0) or 0),
        "nonstandard_edge_type_count": int(diagnostics.get("graph_audit_nonstandard_edge_type_count", 0) or 0),
        "edge_endpoint_issue_count": int(diagnostics.get("graph_audit_edge_endpoint_issue_count", 0) or 0),
        "relation_direction_issue_count": int(diagnostics.get("graph_audit_relation_direction_issue_count", 0) or 0),
        "warning_count": int(diagnostics.get("graph_audit_warning_count", 0) or 0),
    }


def audit_node(state: DocsSyncState) -> DocsSyncState:
    """Audit extracted graph candidates before persistence."""

    started_at = perf_counter()
    payload = state.get("extraction_payload")
    if payload is None:
        return with_node_error(state, "audit_graph", "docs_sync_extraction_payload_missing")

    try:
        audited_payload = audit_knowledge_sync_payload(
            payload,
            structured_context=dict(state.get("structured_context") or {}),
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        return with_node_metrics(
            state,
            "audit_graph",
            _audit_metrics(audited_payload, elapsed_ms=elapsed_ms),
            extraction_payload=audited_payload,
            error=None,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_audit_failed",
            course_id=state.get("course_id"),
            build_session_id=state.get("build_session_id"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_error(
            state,
            "audit_graph",
            str(exc),
            metrics={"elapsed_ms": elapsed_ms},
        )


__all__ = ["audit_node"]
