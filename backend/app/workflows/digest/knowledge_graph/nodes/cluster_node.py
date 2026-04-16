"""Knowledge graph cluster node."""


from __future__ import annotations

from app.shared.infra.database import managed_session
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.knowledge_graph.lib.clusterer import cluster_candidates
from app.workflows.digest.common.models import TopicAnchor, TopicAnchorSnapshot
from app.workflows.digest.knowledge_graph.state import KGDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger

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
            early_snapshot = _build_early_topic_snapshot(state, clustered)

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
                early_topic_anchor_count=len(early_snapshot.anchors),
            )
            return {
                **state,
                "clustered_candidates": clustered,
                "candidate_lookup_to_cluster_id": lookup_to_cluster,
                "topic_anchor_snapshot": early_snapshot,
            }
        except Exception as exc:
            digest_logger.error("kg_workflow_cluster_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"cluster_failed: {exc}"}

__all__ = ["cluster_node"]

