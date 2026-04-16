"""Knowledge graph finalize node."""


from __future__ import annotations

from sqlmodel import select

from app.shared.infra.database import managed_session
from app.models.knowledge_graph import KnowledgeEdge, KnowledgeUnit
from app.repositories import kg_repo
from app.utils.job_helpers import (
    activate_graph_entities_by_job,
    update_job_progress,
)
from app.workflows.digest.knowledge_graph.state import KGDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger
from app.workflows.digest.unified.models import TopicAnchor, TopicAnchorSnapshot
from app.workflows.digest.unified.session import get_unified_build_session


def _build_topic_snapshot(state: KGDigestState) -> TopicAnchorSnapshot:
    chunk_id_to_chunk_uid = state.get("chunk_id_to_chunk_uid", {})
    anchors: list[TopicAnchor] = []
    for cluster in state.get("clustered_candidates", [])[:80]:
        representative = cluster.representative
        if not representative.name or representative.node_type not in {"Topic", "Concept", "Method"}:
            continue
        chunk_uids = [
            chunk_id_to_chunk_uid[chunk_id]
            for chunk_id in cluster.source_chunk_ids
            if chunk_id in chunk_id_to_chunk_uid
        ]
        anchors.append(
            TopicAnchor(
                topic_name=representative.name,
                node_type=representative.node_type,
                confidence=min(0.95, 0.55 + 0.08 * len(cluster.members)),
                chunk_uids=list(dict.fromkeys(chunk_uids)),
            )
        )
    return TopicAnchorSnapshot(anchors=anchors)


def _count_active_graph_entities(*, session, subject: str) -> tuple[int, int]:
    active_node_count = len(
        session.exec(
            select(KnowledgeUnit.id).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status == "active",
            )
        ).all()
    )
    active_edge_count = len(
        session.exec(
            select(KnowledgeEdge.id).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "active",
            )
        ).all()
    )
    return active_node_count, active_edge_count


def build_finalize_graph_node():
    """Build the graph finalize node."""

    async def finalize_graph_node(state: KGDigestState) -> KGDigestState:
        with managed_session() as session:
            digest_logger = workflow_logger(state)
            try:
                job_id = state["job_id"]
                subject = state["subject"]
                build_session_id = state.get("build_session_id", "")
                topic_snapshot = _build_topic_snapshot(state)
                resolved_node_count = max(
                    len(state.get("candidate_lookup_to_resolved_node_id", {})),
                    len(state.get("cluster_id_to_resolved_node_id", {})),
                )
                graph_ready = bool(topic_snapshot.anchors and resolved_node_count > 0)
                if not graph_ready:
                    digest_logger.error(
                        "kg_workflow_finalize_empty_graph",
                        topic_anchor_count=len(topic_snapshot.anchors),
                        resolved_node_count=resolved_node_count,
                        impact_set_present=state.get("impact_set") is not None,
                    )
                    return {
                        **state,
                        "topic_anchor_snapshot": topic_snapshot,
                        "graph_ready": False,
                        "resolved_node_count": resolved_node_count,
                        "error": "finalize_failed: graph_not_usable",
                    }

                activated = activate_graph_entities_by_job(
                    session,
                    job_id=job_id,
                    subject=subject,
                )
                active_node_count, active_edge_count = _count_active_graph_entities(
                    session=session,
                    subject=subject,
                )
                if build_session_id:
                    unified_session = get_unified_build_session(build_session_id)
                    unified_session.publish_topic_anchor_snapshot(topic_snapshot)

                kg_repo.release_subject_build_lock(session, subject)
                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="completed",
                )
                update_job_progress(
                    session,
                    job_id=job_id,
                    job_type="graph",
                    progress=100,
                    current_step="finalize_graph",
                )
                digest_logger.info(
                    "kg_workflow_finalize_complete",
                    activated=activated,
                    topic_anchor_count=len(topic_snapshot.anchors),
                    resolved_node_count=resolved_node_count,
                    active_node_count=active_node_count,
                    active_edge_count=active_edge_count,
                )
                return {
                    **state,
                    "topic_anchor_snapshot": topic_snapshot,
                    "graph_ready": True,
                    "resolved_node_count": resolved_node_count,
                    "active_node_count": active_node_count,
                    "active_edge_count": active_edge_count,
                    "error": None,
                }
            except Exception as exc:
                session.rollback()
                digest_logger.error("kg_workflow_finalize_failed", error=str(exc), exc_info=True)
                return {**state, "error": f"finalize_failed: {exc}"}

    return finalize_graph_node

__all__ = ["build_finalize_graph_node"]

