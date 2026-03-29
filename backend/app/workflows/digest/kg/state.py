"""Typed state for the graph lane."""

from __future__ import annotations

from typing import Any, TypedDict

from app.workflows.digest.kg.services.clusterer import ClusteredCandidate
from app.workflows.digest.kg.services.extractor import CandidateEdge, ChunkExtractionResult
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet


class KGDigestState(TypedDict, total=False):
    """State carried by the knowledge-graph digest graph."""

    subject: str
    file_ids: list[int]
    job_id: int
    build_session_id: str
    shared_inputs: Any
    chunk_ids: list[int]
    chunk_uid_to_chunk_id: dict[str, int]
    chunk_id_to_chunk_uid: dict[int, str]

    candidates: list[ChunkExtractionResult]
    all_candidate_edges: list[tuple[CandidateEdge, int]]
    clustered_candidates: list[ClusteredCandidate]
    candidate_name_to_cluster_id: dict[str, int]
    candidate_name_to_resolved_node_id: dict[str, int]
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
    lock_acquired: bool
    error: str | None
