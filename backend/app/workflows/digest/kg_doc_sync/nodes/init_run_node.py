"""Docs-sync run initialization node."""

from __future__ import annotations

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import initialize_knowledge_graph_sync_run
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def init_run_node(state: DocsSyncState) -> DocsSyncState:
    try:
        with managed_session() as session:
            run_context = initialize_knowledge_graph_sync_run(
                session,
                subject=state["subject"],
                markdown=state["markdown"],
                build_revision_no=state.get("build_revision_no"),
                structured_context=dict(state.get("structured_context") or {}),
                build_session_id=state.get("build_session_id"),
            )
        return {
            **state,
            "build_revision_no": run_context.build_revision_no,
            "structured_context": run_context.structured_context,
            "sync_run_context": run_context,
            "error": None,
        }
    except Exception as exc:
        logger.warning(
            "kg_doc_sync_init_run_failed",
            subject=state.get("subject"),
            build_session_id=state.get("build_session_id"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {**state, "sync_run_context": None, "error": str(exc)}


__all__ = ["init_run_node"]
