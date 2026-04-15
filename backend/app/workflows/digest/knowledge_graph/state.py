"""Typed state for the graph lane."""

from __future__ import annotations

from typing import Any, TypedDict

from app.workflows.digest.knowledge_graph.services.clusterer import ClusteredCandidate
from app.workflows.digest.knowledge_graph.services.extractor import CandidateEdge, ChunkExtractionResult
from app.workflows.digest.knowledge_graph.services.impact_analyzer import ImpactSet


class KGDigestState(TypedDict, total=False):
    """State carried by the knowledge-graph digest graph."""

    subject: str
    file_ids: list[int]
    job_id: int
    build_session_id: str
    doc_chapter_metadatas: list[dict[str, Any]]
    shared_inputs: Any
    chunk_ids: list[int]
    chunk_uid_to_chunk_id: dict[str, int]
    chunk_id_to_chunk_uid: dict[int, str]

    candidates: list[ChunkExtractionResult]
    all_candidate_edges: list[tuple[CandidateEdge, int]]
    clustered_candidates: list[ClusteredCandidate]
    candidate_lookup_to_cluster_id: dict[str, int]
    candidate_lookup_to_resolved_node_id: dict[str, int]
    cluster_id_to_resolved_node_id: dict[int, int]
    new_node_ids: list[int]
    updated_node_ids: list[int]
    merged_node_ids: list[int]
    new_edge_ids: list[int]
    updated_edge_ids: list[int]
    impact_set: ImpactSet | None
    topic_anchor_snapshot: Any
    graph_ready: bool
    resolved_node_count: int
    active_node_count: int
    active_edge_count: int
    acquire_lock_ms: int
    prepare_ms: int
    extract_ms: int
    cluster_ms: int
    resolve_nodes_ms: int
    resolve_edges_ms: int
    impact_ms: int
    finalize_ms: int
    resolution_index_ms: int
    candidate_embedding_ms: int
    node_persist_ms: int
    edge_persist_ms: int
    fast_path_chunk_count: int
    llm_extract_chunk_count: int
    success_chunk_count: int
    failed_chunk_count: int
    doc_summary_extraction_count: int
    doc_summary_node_count: int
    doc_summary_edge_count: int
    no_match_count: int
    secondary_no_match_count: int
    unresolved_endpoint_count: int
    slowest_chunks: list[dict[str, Any]]
    timing_summary: dict[str, Any]
    token_summary: dict[str, Any]
    lock_acquired: bool
    error: str | None

