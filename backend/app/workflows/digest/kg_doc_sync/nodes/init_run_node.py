"""Docs-sync run initialization node."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import initialize_knowledge_graph_sync_run
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncRunContext
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def _run_metrics(run_context: KnowledgeSyncRunContext, *, elapsed_ms: int) -> dict[str, object]:
    return {
        "ok": True,
        "sync_run_id": run_context.sync_run_id,
        "build_revision_no": run_context.build_revision_no,
        "doc_version_no": run_context.doc_version_no,
        "structured_context_keys": sorted(run_context.structured_context.keys()),
        "elapsed_ms": elapsed_ms,
    }


def init_run_node(state: DocsSyncState) -> DocsSyncState:
    started_at = perf_counter()
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
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        return with_node_metrics(
            state,
            "init_run",
            _run_metrics(run_context, elapsed_ms=elapsed_ms),
            build_revision_no=run_context.build_revision_no,
            structured_context=run_context.structured_context,
            sync_run_context=run_context,
            error=None,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_init_run_failed",
            subject=state.get("subject"),
            build_session_id=state.get("build_session_id"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_error(
            state,
            "init_run",
            str(exc),
            metrics={"elapsed_ms": elapsed_ms},
            sync_run_context=None,
        )


__all__ = ["init_run_node"]
