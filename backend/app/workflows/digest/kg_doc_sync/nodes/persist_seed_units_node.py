"""Docs-sync 最早可用知识点写入节点。"""

from __future__ import annotations

import asyncio
import inspect
from time import perf_counter

import structlog

from app.shared.infra.workflow.live_stream import publish_workflow_stream_event
from app.utils.time import utcnow
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import (
    build_prefetched_knowledge_graph_units_payload,
    persist_knowledge_graph_units_early,
)
from app.workflows.digest.kg_doc_sync.nodes.node_state import managed_build_owner_transaction, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def _seed_source_from_diagnostics(diagnostics: dict[str, object]) -> str:
    prefetch_units = int(diagnostics.get("prefetch_early_unit_count", 0) or 0)
    docgen_seed_units = int(diagnostics.get("docgen_seed_unit_count", 0) or 0)
    if prefetch_units > 0 and docgen_seed_units > 0:
        return "prefetch_and_structural_anchor"
    if docgen_seed_units > 0:
        return "structural_anchor"
    return "prefetch"


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
    """在正式抽取前，提前写入结构锚点和已预取知识点。"""

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
        payload = prefetched_payload
        diagnostics = dict(payload.diagnostics_totals or {})
        seed_source = _seed_source_from_diagnostics(diagnostics)
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
                    "docgen_seed_unit_count": int(diagnostics.get("docgen_seed_unit_count", 0) or 0),
                    "early_units_callback_requested": False,
                },
                error=None,
            )

        with managed_build_owner_transaction(state) as session:
            metrics = persist_knowledge_graph_units_early(
                session,
                run_context=run_context,
                payload=payload,
            )
        publish_workflow_stream_event(
            run_context.course_id,
            "graph_delta",
            {
                "stage": "persist_seed_units",
                "build_revision_no": run_context.build_revision_no,
                "unit_count": int(metrics.get("unit_count", 0) or 0),
                "created_unit_count": int(metrics.get("created_unit_count", 0) or 0),
                "updated_unit_count": int(metrics.get("updated_unit_count", 0) or 0),
                "edge_count": int(metrics.get("edge_count", 0) or 0),
                "created_edge_count": int(metrics.get("created_edge_count", 0) or 0),
                "updated_edge_count": int(metrics.get("updated_edge_count", 0) or 0),
                "deprecated_edge_count": 0,
                "emitted_at": utcnow().isoformat(),
            },
        )
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
