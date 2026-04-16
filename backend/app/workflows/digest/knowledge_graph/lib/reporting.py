"""Knowledge-graph lane reporting helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.workflows.digest.shared.metrics import (
    DigestTokenSummary,
    build_lane_llm_rollup,
    build_slow_items,
)


def build_knowledge_lane_summary(
    state: Mapping[str, Any],
    *,
    token_summary: DigestTokenSummary,
    status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Create a knowledge-graph lane summary payload."""

    resolved_status = _resolve_status(state, status=status, error_message=error_message)
    resolved_error = _resolve_error_message(state, error_message=error_message)
    extract_tokens = int(token_summary.tokens_by_node.get("extract", 0))
    resolve_tokens = int(token_summary.tokens_by_node.get("resolve_nodes", 0)) + int(
        token_summary.tokens_by_node.get("resolve_edges", 0)
    )
    return {
        "status": resolved_status,
        "error_message": resolved_error,
        "chunk_count": len(state.get("chunk_ids", [])),
        "cluster_count": len(state.get("clustered_candidates", [])),
        "resolved_node_count": int(state.get("resolved_node_count", 0)),
        "active_node_count": int(state.get("active_node_count", 0)),
        "active_edge_count": int(state.get("active_edge_count", 0)),
        "workflow_elapsed_ms": int(state.get("workflow_elapsed_ms", 0)),
        "acquire_lock_ms": int(state.get("acquire_lock_ms", 0)),
        "prepare_ms": int(state.get("prepare_ms", 0)),
        "extract_ms": int(state.get("extract_ms", 0)),
        "cluster_ms": int(state.get("cluster_ms", 0)),
        "resolve_nodes_ms": int(state.get("resolve_nodes_ms", 0)),
        "resolve_edges_ms": int(state.get("resolve_edges_ms", 0)),
        "impact_ms": int(state.get("impact_ms", 0)),
        "finalize_ms": int(state.get("finalize_ms", 0)),
        "resolution_index_ms": int(state.get("resolution_index_ms", 0)),
        "candidate_embedding_ms": int(state.get("candidate_embedding_ms", 0)),
        "node_persist_ms": int(state.get("node_persist_ms", 0)),
        "edge_persist_ms": int(state.get("edge_persist_ms", 0)),
        "fast_path_chunk_count": int(state.get("fast_path_chunk_count", 0)),
        "llm_extract_chunk_count": int(state.get("llm_extract_chunk_count", 0)),
        "success_chunk_count": int(state.get("success_chunk_count", 0)),
        "failed_chunk_count": int(state.get("failed_chunk_count", 0)),
        "no_match_count": int(state.get("no_match_count", 0)),
        "secondary_no_match_count": int(state.get("secondary_no_match_count", 0)),
        "unresolved_endpoint_count": int(state.get("unresolved_endpoint_count", 0)),
        "extract_total_tokens": extract_tokens,
        "resolve_total_tokens": resolve_tokens,
        **build_lane_llm_rollup(token_summary),
        "slowest_chunks_top_k": [item.model_dump() for item in build_slow_items(state.get("slowest_chunks", []))],
    }


def _resolve_status(
    state: Mapping[str, Any],
    *,
    status: str | None,
    error_message: str | None,
) -> str:
    if status:
        return status
    if error_message or state.get("error"):
        return "failed"
    if not state:
        return "ok"
    return "ok"


def _resolve_error_message(state: Mapping[str, Any], *, error_message: str | None) -> str | None:
    resolved = error_message or str(state.get("error", "")).strip()
    return resolved or None


__all__ = ["build_knowledge_lane_summary"]
