"""Digest graph workflow state types."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.digest.kg.services.clusterer import ClusteredCandidate
from app.workflows.digest.kg.services.extractor import CandidateEdge, ChunkExtractionResult
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet


class KGDigestState(TypedDict, total=False):
    subject: str
    file_ids: list[int]
    job_id: int
    chunk_ids: list[int]
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
    lock_acquired: bool
    error: str | None


__all__ = ["KGDigestState"]
