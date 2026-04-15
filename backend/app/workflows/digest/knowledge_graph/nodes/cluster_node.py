"""Knowledge graph cluster node."""


from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from sqlmodel import select

from app.shared.infra.config import get_settings
from app.shared.infra.database import managed_session
from app.models import RetrievalChunk
from app.repositories.knowledge import kg_repo
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.knowledge_graph.lib.candidate_identity import candidate_lookup_keys
from app.workflows.digest.knowledge_graph.lib.clusterer import cluster_candidates
from app.workflows.digest.knowledge_graph.lib.extractor import (
    CandidateEdge,
    ChunkExtractionResult,
    extract_candidates,
    has_conceptual_content,
)
from app.workflows.digest.shared.metrics import add_slow_item
from app.workflows.digest.knowledge_graph.state import KGDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger
from app.shared.infra.workflow.runtime import cancel_tasks_and_drain
from app.workflows.digest.unified.models import ChapterPriors, TopicAnchor, TopicAnchorSnapshot
from app.workflows.digest.unified.session import get_unified_build_session

def _build_early_topic_snapshot(state: KGDigestState, clustered_candidates) -> TopicAnchorSnapshot:
    chunk_id_to_chunk_uid = state.get("chunk_id_to_chunk_uid", {})
    anchors: list[TopicAnchor] = []
    for cluster in clustered_candidates[:80]:
        representative = cluster.representative
        if not representative.name or representative.node_type not in {"Topic", "Concept", "Method"}:
            continue
        chunk_uids = [
            chunk_id_to_chunk_uid[chunk_id]
            for chunk_id in cluster.source_chunk_ids
            if chunk_id in chunk_id_to_chunk_uid
        ]
        if not chunk_uids:
            continue
        anchors.append(
            TopicAnchor(
                topic_name=representative.name,
                node_type=representative.node_type,
                confidence=min(0.9, 0.5 + 0.06 * len(cluster.members)),
                chunk_uids=list(dict.fromkeys(chunk_uids)),
            )
        )
    return TopicAnchorSnapshot(anchors=anchors)

async def cluster_node(state: KGDigestState) -> KGDigestState:
    """Cluster candidate nodes within the current batch."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            results = state.get("candidates", [])
            chunk_ids = state.get("chunk_ids", [])
            digest_logger.info(
                "kg_cluster_started",
                result_count=len(results),
                chunk_count=len(chunk_ids),
            )

            all_pairs = [
                (node, chunk_id)
                for chunk_id, result in zip(chunk_ids, results)
                for node in result.nodes
            ]
            if not all_pairs:
                update_job_progress(
                    session,
                    job_id=state["job_id"],
                    job_type="graph",
                    progress=50,
                    current_step="cluster",
                )
                return {
                    **state,
                    "clustered_candidates": [],
                    "candidate_lookup_to_cluster_id": {},
                }

            clustered, lookup_to_cluster = await cluster_candidates(all_pairs)
            build_session_id = state.get("build_session_id", "")
            if build_session_id:
                unified_session = get_unified_build_session(build_session_id)
                early_snapshot = _build_early_topic_snapshot(state, clustered)
                unified_session.publish_topic_anchor_snapshot(early_snapshot)

            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=50,
                current_step="cluster",
            )
            digest_logger.info(
                "kg_workflow_cluster_complete",
                input_candidates=len(all_pairs),
                cluster_count=len(clustered),
                early_topic_anchor_count=len(early_snapshot.anchors) if build_session_id else 0,
            )
            return {
                **state,
                "clustered_candidates": clustered,
                "candidate_lookup_to_cluster_id": lookup_to_cluster,
            }
        except Exception as exc:
            digest_logger.error("kg_workflow_cluster_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"cluster_failed: {exc}"}

__all__ = ["cluster_node"]
