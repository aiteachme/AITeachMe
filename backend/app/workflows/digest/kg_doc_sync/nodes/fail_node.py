"""Docs-sync fail node."""

from __future__ import annotations

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import mark_knowledge_graph_sync_run_failed
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def fail_node(state: DocsSyncState) -> DocsSyncState:
    run_context = state.get("sync_run_context")
    if run_context is None:
        return state

    try:
        with managed_session() as session:
            mark_knowledge_graph_sync_run_failed(
                session,
                sync_run_id=run_context.sync_run_id,
                error_message=str(state.get("error") or "docs_sync_failed"),
            )
    except Exception as exc:
        logger.warning(
            "kg_doc_sync_fail_marker_failed",
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
    return state


__all__ = ["fail_node"]
