"""Docs-sync 提前写入知识点节点。"""

from __future__ import annotations

import asyncio
import inspect
from time import perf_counter

import structlog

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import persist_knowledge_graph_units_early
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


async def persist_units_node(state: DocsSyncState) -> DocsSyncState:
    """在较重的图谱收口前，先发布已抽取出的 KnowledgeUnit。"""

    started_at = perf_counter()
    run_context = state.get("sync_run_context")
    payload = state.get("extraction_payload")
    if run_context is None:
        return with_node_error(state, "persist_units", "docs_sync_run_context_missing")
    if payload is None:
        return with_node_error(state, "persist_units", "docs_sync_extraction_payload_missing")

    try:
        with managed_session() as session:
            metrics = persist_knowledge_graph_units_early(
                session,
                run_context=run_context,
                payload=payload,
            )
        callback = state.get("early_units_callback")
        seed_already_covers_final_exam = bool(
            state.get("early_units_callback_requested") and state.get("early_units_seed_complete")
        )
        if callable(callback) and int(metrics.get("unit_count", 0) or 0) > 0 and not seed_already_covers_final_exam:
            try:
                callback_result = callback(
                    course_id=run_context.course_id,
                    build_revision_no=run_context.build_revision_no,
                    metrics=dict(metrics),
                )
                if inspect.isawaitable(callback_result):
                    await callback_result
                await asyncio.sleep(0)
                metrics["early_units_callback_requested"] = True
            except Exception as callback_exc:
                metrics["early_units_callback_requested"] = False
                metrics["early_units_callback_error"] = str(callback_exc)
                logger.warning(
                    "kg_doc_sync_early_units_callback_failed",
                    course_id=state.get("course_id"),
                    build_session_id=state.get("build_session_id"),
                    sync_run_id=run_context.sync_run_id,
                    error_type=type(callback_exc).__name__,
                    error=str(callback_exc),
                )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        return with_node_metrics(
            state,
            "persist_units",
            {
                "ok": True,
                "elapsed_ms": elapsed_ms,
                "early_units_callback_skipped": seed_already_covers_final_exam,
                **metrics,
            },
            error=None,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_persist_units_early_failed",
            course_id=state.get("course_id"),
            build_session_id=state.get("build_session_id"),
            sync_run_id=run_context.sync_run_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_metrics(
            state,
            "persist_units",
            {
                "ok": False,
                "non_blocking": True,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            },
            error=None,
        )


__all__ = ["persist_units_node"]
