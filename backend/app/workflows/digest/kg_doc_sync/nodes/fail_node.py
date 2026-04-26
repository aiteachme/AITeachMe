"""Docs-sync fail node."""

from __future__ import annotations

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.sync_runs import mark_knowledge_graph_sync_run_failed
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def fail_node(state: DocsSyncState) -> DocsSyncState:
    run_context = state.get("sync_run_context")
    error_message = str(state.get("error") or "docs_sync_failed")
    if run_context is None:
        return with_node_metrics(
            state,
            "fail",
            {
                "ok": False,
                "error": error_message,
                "sync_run_marked_failed": False,
                "reason": "sync_run_context_missing",
            },
        )

    try:
        with managed_session() as session:
            mark_knowledge_graph_sync_run_failed(
                session,
                sync_run_id=run_context.sync_run_id,
                error_message=error_message,
            )
        return with_node_metrics(
            state,
            "fail",
            {
                "ok": False,
                "error": error_message,
                "sync_run_id": run_context.sync_run_id,
                "sync_run_marked_failed": True,
            },
        )
    except Exception as exc:
        logger.warning(
            "kg_doc_sync_fail_marker_failed",
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_metrics(
            state,
            "fail",
            {
                "ok": False,
                "error": error_message,
                "sync_run_id": run_context.sync_run_id,
                "sync_run_marked_failed": False,
                "fail_marker_error": str(exc),
            },
        )


__all__ = ["fail_node"]
