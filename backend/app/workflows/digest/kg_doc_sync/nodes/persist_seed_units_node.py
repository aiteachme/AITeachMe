"""Docs-sync 最早可用知识点写入节点。"""

from __future__ import annotations

import asyncio
import inspect
from time import perf_counter

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import (
    build_prefetched_knowledge_graph_units_payload,
    persist_knowledge_graph_units_early,
)
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


async def _notify_early_units_callback(
    state: DocsSyncState,
    *,
    build_revision_no: int,
    metrics: dict[str, object],
) -> tuple[bool, str]:
    callback = state.get("early_units_callback")
    if not callable(callback):
        return False, ""
    try:
        callback_result = callback(
            course_id=state["course_id"],
            build_revision_no=build_revision_no,
            metrics=dict(metrics),
        )
        if inspect.isawaitable(callback_result):
            await callback_result
        await asyncio.sleep(0)
        return True, ""
    except Exception as exc:
        logger.warning(
            "kg_doc_sync_seed_units_callback_failed",
            course_id=state.get("course_id"),
            build_session_id=state.get("build_session_id"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False, str(exc)


async def persist_seed_units_node(state: DocsSyncState) -> DocsSyncState:
    """在正式抽取前，只提前写入 DocGen LLM 预抽取命中的种子知识点。"""

    started_at = perf_counter()
    run_context = state.get("sync_run_context")
    if run_context is None:
        return with_node_metrics(
            state,
            "persist_seed_units",
            {
                "ok": False,
                "non_blocking": True,
                "error": "docs_sync_run_context_missing",
            },
            error=None,
        )

    try:
        prefetched_payload = build_prefetched_knowledge_graph_units_payload(
            markdown=state["markdown"],
            structured_context=dict(state.get("structured_context") or {}),
            prefetched_records=list(state.get("prefetched_sections") or []),
        )
        seed_source = "prefetch"
        payload = prefetched_payload
        if not payload.units:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            return with_node_metrics(
                state,
                "persist_seed_units",
                {
                    "ok": True,
                    "elapsed_ms": elapsed_ms,
                    "seed_source": seed_source,
                    "unit_count": 0,
                    "non_llm_seed_skipped": True,
                    "early_units_callback_requested": False,
                },
                error=None,
            )

        with managed_session() as session:
            metrics = persist_knowledge_graph_units_early(
                session,
                run_context=run_context,
                payload=payload,
            )
        diagnostics = dict(payload.diagnostics_totals or {})
        prefetch_complete = bool(int(diagnostics.get("prefetch_complete_section_coverage", 0) or 0))
        callback_requested, callback_error = await _notify_early_units_callback(
            state,
            build_revision_no=run_context.build_revision_no,
            metrics={
                **metrics,
                "seed_source": seed_source,
                "prefetch_complete_section_coverage": prefetch_complete,
            },
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        return with_node_metrics(
            state,
            "persist_seed_units",
            {
                "ok": True,
                "elapsed_ms": elapsed_ms,
                "seed_source": seed_source,
                "prefetch_complete_section_coverage": prefetch_complete,
                "early_units_callback_requested": callback_requested,
                "early_units_callback_error": callback_error,
                **metrics,
                **diagnostics,
            },
            early_units_callback_requested=callback_requested,
            early_units_seed_complete=(callback_requested and seed_source == "prefetch" and prefetch_complete),
            error=None,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_persist_seed_units_failed",
            course_id=state.get("course_id"),
            build_session_id=state.get("build_session_id"),
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_metrics(
            state,
            "persist_seed_units",
            {
                "ok": False,
                "non_blocking": True,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            },
            error=None,
        )


__all__ = ["persist_seed_units_node"]
