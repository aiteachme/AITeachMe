"""Docs-sync graph-item extraction node."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import (
    extract_knowledge_graph_items_async,
    graph_extraction_parallelism,
)
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncExtractionPayload
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState
from app.workflows.support.subjects.learning_context import load_subject_llm_context

logger = structlog.get_logger()


def _load_subject_context(state: DocsSyncState) -> tuple[str, str]:
    subject_context = str(state.get("subject_context") or "").strip()
    if subject_context:
        return subject_context, "state"
    with managed_session() as session:
        return load_subject_llm_context(session, subject=state["subject"]), "database"


def _payload_metrics(
    payload: KnowledgeSyncExtractionPayload,
    *,
    elapsed_ms: int,
    subject_context_source: str,
) -> dict[str, object]:
    diagnostics = dict(payload.diagnostics_totals or {})
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "subject_context_source": subject_context_source,
        "unit_count": len(payload.units),
        "edge_count": len(payload.extracted_edges),
        "chapter_count": int(diagnostics.get("chapter_count", 0) or 0),
        "section_count": int(diagnostics.get("section_count", 0) or 0),
        "chapter_split_count": int(diagnostics.get("chapter_split_count", 0) or 0),
        "chapter_task_count": int(diagnostics.get("chapter_task_count", 0) or 0),
        "subsection_task_count": int(diagnostics.get("subsection_task_count", 0) or 0),
        "successful_section_count": int(diagnostics.get("successful_section_count", 0) or 0),
        "failed_section_count": int(diagnostics.get("failed_section_count", 0) or 0),
        "llm_section_count": int(diagnostics.get("llm_section_count", 0) or 0),
        "llm_error_count": int(diagnostics.get("llm_error_count", 0) or 0),
        "empty_llm_result_count": int(diagnostics.get("empty_llm_result_count", 0) or 0),
        "empty_repair_attempt_count": int(diagnostics.get("empty_repair_attempt_count", 0) or 0),
        "empty_repair_success_count": int(diagnostics.get("empty_repair_success_count", 0) or 0),
        **graph_extraction_parallelism(),
    }


async def extract_node(state: DocsSyncState) -> DocsSyncState:
    started_at = perf_counter()
    run_context = state.get("sync_run_context")
    if run_context is None:
        return with_node_error(
            state,
            "extract",
            "docs_sync_run_context_missing",
            metrics=graph_extraction_parallelism(),
        )

    try:
        subject_context, subject_context_source = _load_subject_context(state)
        payload = await extract_knowledge_graph_items_async(
            markdown=state["markdown"],
            subject_context=subject_context,
            run_context=run_context,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        if payload is None:
            return with_node_error(
                state,
                "extract",
                "docs_sync_extraction_payload_missing",
                metrics={
                    "elapsed_ms": elapsed_ms,
                    "subject_context_source": subject_context_source,
                    **graph_extraction_parallelism(),
                },
                subject_context=subject_context,
                extraction_payload=None,
            )
        return with_node_metrics(
            state,
            "extract",
            _payload_metrics(
                payload,
                elapsed_ms=elapsed_ms,
                subject_context_source=subject_context_source,
            ),
            subject_context=subject_context,
            extraction_payload=payload,
            error=None,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_extract_failed",
            subject=state.get("subject"),
            build_session_id=state.get("build_session_id"),
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_error(
            state,
            "extract",
            str(exc),
            metrics={"elapsed_ms": elapsed_ms, **graph_extraction_parallelism()},
            extraction_payload=None,
        )


__all__ = ["extract_node"]
