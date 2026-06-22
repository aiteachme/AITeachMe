"""Docs-sync graph-item extraction node."""

from __future__ import annotations

import asyncio
from time import perf_counter

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import (
    build_docgen_kg_draft_final_payload,
    extract_knowledge_graph_items_async,
    graph_extraction_parallelism,
)
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncExtractionPayload
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState
from app.workflows.support.courses.learning_context import load_course_llm_context

logger = structlog.get_logger()


def _load_course_context(state: DocsSyncState) -> tuple[str, str]:
    course_context = str(state.get("course_context") or "").strip()
    if course_context:
        return course_context, "state"
    with managed_session() as session:
        return load_course_llm_context(session, course_id=state["course_id"]), "database"


def _payload_metrics(
    payload: KnowledgeSyncExtractionPayload,
    *,
    elapsed_ms: int,
    course_context_source: str,
) -> dict[str, object]:
    diagnostics = dict(payload.diagnostics_totals or {})
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "course_context_source": course_context_source,
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
        "rule_fallback_attempt_count": int(diagnostics.get("rule_fallback_attempt_count", 0) or 0),
        "rule_fallback_success_count": int(diagnostics.get("rule_fallback_success_count", 0) or 0),
        "prefetch_section_count": int(diagnostics.get("prefetch_section_count", 0) or 0),
        "prefetch_reused_section_count": int(diagnostics.get("prefetch_reused_section_count", 0) or 0),
        "prefetch_catchup_section_count": int(diagnostics.get("prefetch_catchup_section_count", 0) or 0),
        "prefetch_stale_section_count": int(diagnostics.get("prefetch_stale_section_count", 0) or 0),
        "prefetch_failed_section_count": int(diagnostics.get("prefetch_failed_section_count", 0) or 0),
        "docgen_draft_fast_finalize": int(diagnostics.get("docgen_draft_fast_finalize", 0) or 0),
        "docgen_draft_final_unit_count": int(diagnostics.get("docgen_draft_final_unit_count", 0) or 0),
        "docgen_draft_final_edge_count": int(diagnostics.get("docgen_draft_final_edge_count", 0) or 0),
        "docgen_draft_final_skipped_edge_count": int(diagnostics.get("docgen_draft_final_skipped_edge_count", 0) or 0),
        **graph_extraction_parallelism(),
    }


async def extract_node(state: DocsSyncState) -> DocsSyncState:
    """Fan out markdown sections into LLM extraction tasks and fan in candidates.

    This node intentionally does not write graph tables. It only returns an
    extraction payload plus diagnostics, so partial section failures can still
    be persisted with the successful sections.
    """

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
        fast_payload = build_docgen_kg_draft_final_payload(
            markdown=state["markdown"],
            structured_context=state.get("structured_context"),
        )
        if fast_payload is not None:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            return with_node_metrics(
                state,
                "extract",
                _payload_metrics(
                    fast_payload,
                    elapsed_ms=elapsed_ms,
                    course_context_source="docgen_kg_draft",
                ),
                course_context=state.get("course_context") or "",
                extraction_payload=fast_payload,
                error=None,
            )

        course_context, course_context_source = _load_course_context(state)
        payload = await extract_knowledge_graph_items_async(
            markdown=state["markdown"],
            course_context=course_context,
            run_context=run_context,
            prefetched_records=(
                list(state.get("prefetched_sections") or [])
                if state.get("prefetched_sections")
                else None
            ),
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        if payload is None:
            return with_node_error(
                state,
                "extract",
                "docs_sync_extraction_payload_missing",
                metrics={
                    "elapsed_ms": elapsed_ms,
                    "course_context_source": course_context_source,
                    **graph_extraction_parallelism(),
                },
                course_context=course_context,
                extraction_payload=None,
            )
        return with_node_metrics(
            state,
            "extract",
            _payload_metrics(
                payload,
                elapsed_ms=elapsed_ms,
                course_context_source=course_context_source,
            ),
            course_context=course_context,
            extraction_payload=payload,
            error=None,
        )
    except asyncio.CancelledError:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_extract_cancelled",
            course_id=state.get("course_id"),
            build_session_id=state.get("build_session_id"),
            sync_run_id=run_context.sync_run_id,
            elapsed_ms=elapsed_ms,
            **graph_extraction_parallelism(),
        )
        raise
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_extract_failed",
            course_id=state.get("course_id"),
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
