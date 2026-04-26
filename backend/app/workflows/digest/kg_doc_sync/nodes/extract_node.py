"""Docs-sync graph-item extraction node."""

from __future__ import annotations

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import extract_knowledge_graph_items
from app.workflows.digest.kg_doc_sync.state import DocsSyncState
from app.workflows.support.subjects.learning_context import load_subject_llm_context

logger = structlog.get_logger()


def extract_node(state: DocsSyncState) -> DocsSyncState:
    run_context = state.get("sync_run_context")
    if run_context is None:
        return {**state, "error": "docs_sync_run_context_missing"}

    try:
        subject_context = str(state.get("subject_context") or "").strip()
        if not subject_context:
            with managed_session() as session:
                subject_context = load_subject_llm_context(session, subject=state["subject"])
        payload = extract_knowledge_graph_items(
            markdown=state["markdown"],
            subject_context=subject_context,
            run_context=run_context,
        )
        return {
            **state,
            "subject_context": subject_context,
            "extraction_payload": payload,
            "error": None,
        }
    except Exception as exc:
        logger.warning(
            "kg_doc_sync_extract_failed",
            subject=state.get("subject"),
            build_session_id=state.get("build_session_id"),
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {**state, "extraction_payload": None, "error": str(exc)}


__all__ = ["extract_node"]
