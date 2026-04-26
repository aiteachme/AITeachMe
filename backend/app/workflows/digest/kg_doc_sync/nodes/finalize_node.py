"""Docs-sync finalize node."""

from __future__ import annotations

from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncReport
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState


def _final_report_metrics(report: KnowledgeSyncReport) -> dict[str, object]:
    return {
        "ok": True,
        "sync_run_id": report.sync_run_id,
        "build_revision_no": report.build_revision_no,
        "doc_version_no": report.doc_version_no,
        "chapter_count": report.chapter_count,
        "section_count": report.section_count,
        "synced_unit_count": len(report.synced_unit_keys),
        "unit_change_count": report.unit_change_count,
        "edge_change_count": report.edge_change_count,
        "source_ref_count": report.source_ref_count,
        "elapsed_ms": report.elapsed_ms,
    }


def finalize_node(state: DocsSyncState) -> DocsSyncState:
    report = state.get("report")
    if report is None and not state.get("error"):
        return with_node_error(state, "finalize", "docs_sync_report_missing")
    if report is None:
        return with_node_metrics(
            state,
            "finalize",
            {
                "ok": False,
                "error": str(state.get("error") or "docs_sync_failed"),
                "report_present": False,
            },
        )
    return with_node_metrics(state, "finalize", _final_report_metrics(report), error=None)


__all__ = ["finalize_node"]
