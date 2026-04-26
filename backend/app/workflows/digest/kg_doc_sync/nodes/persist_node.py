"""Docs-sync graph persistence node."""

from __future__ import annotations

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import persist_knowledge_graph_items
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def persist_node(state: DocsSyncState) -> DocsSyncState:
    run_context = state.get("sync_run_context")
    payload = state.get("extraction_payload")
    if run_context is None:
        return {**state, "error": "docs_sync_run_context_missing"}
    if payload is None:
        return {**state, "error": "docs_sync_extraction_payload_missing"}

    try:
        with managed_session() as session:
            report = persist_knowledge_graph_items(
                session,
                run_context=run_context,
                payload=payload,
            )
        return {**state, "report": report, "error": None}
    except Exception as exc:
        logger.warning(
            "kg_doc_sync_persist_failed",
            subject=state.get("subject"),
            build_session_id=state.get("build_session_id"),
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {**state, "report": None, "error": str(exc)}


__all__ = ["persist_node"]
