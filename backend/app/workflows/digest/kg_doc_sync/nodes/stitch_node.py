"""Docs-sync relation stitching node.

This node sits between extraction and persistence. It adds conservative,
no-LLM relation edges among already extracted KnowledgeUnit candidates so the
graph is less fragmented before rows are written.
"""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncExtractionPayload
from app.workflows.digest.kg_doc_sync.lib.relation_stitching import stitch_knowledge_graph_relations
from app.workflows.digest.kg_doc_sync.nodes.node_state import with_node_error, with_node_metrics
from app.workflows.digest.kg_doc_sync.state import DocsSyncState

logger = structlog.get_logger()


def _stitch_metrics(payload: KnowledgeSyncExtractionPayload, *, elapsed_ms: int) -> dict[str, object]:
    diagnostics = dict(payload.diagnostics_totals or {})
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "unit_count": len(payload.units),
        "edge_count": len(payload.extracted_edges),
        "stitched_edge_count": int(diagnostics.get("stitched_edge_count", 0) or 0),
        "section_local_stitch_edge_count": int(diagnostics.get("section_local_stitch_edge_count", 0) or 0),
        "mention_stitch_edge_count": int(diagnostics.get("mention_stitch_edge_count", 0) or 0),
        "graph_isolated_unit_count": int(diagnostics.get("graph_isolated_unit_count", 0) or 0),
        "graph_component_count": int(diagnostics.get("graph_component_count", 0) or 0),
        "graph_largest_component_unit_count": int(diagnostics.get("graph_largest_component_unit_count", 0) or 0),
        "graph_avg_degree": float(diagnostics.get("graph_avg_degree", 0.0) or 0.0),
        "graph_isolated_unit_pct": float(diagnostics.get("graph_isolated_unit_pct", 0.0) or 0.0),
    }


def stitch_node(state: DocsSyncState) -> DocsSyncState:
    """Stitch extracted section candidates with deterministic relation edges."""

    started_at = perf_counter()
    payload = state.get("extraction_payload")
    if payload is None:
        return with_node_error(state, "stitch_relations", "docs_sync_extraction_payload_missing")

    try:
        stitched_payload = stitch_knowledge_graph_relations(payload)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        return with_node_metrics(
            state,
            "stitch_relations",
            _stitch_metrics(stitched_payload, elapsed_ms=elapsed_ms),
            extraction_payload=stitched_payload,
            error=None,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "kg_doc_sync_stitch_failed",
            subject_id=state.get("subject_id"),
            build_session_id=state.get("build_session_id"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return with_node_error(
            state,
            "stitch_relations",
            str(exc),
            metrics={"elapsed_ms": elapsed_ms},
        )


__all__ = ["stitch_node"]
