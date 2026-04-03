"""Finalize and failure nodes for the graph lane."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from collections.abc import Awaitable, Callable

from sqlmodel import select

from app.core.database import managed_session
from app.models.knowledge_graph import KnowledgeEdge, KnowledgeNode
from app.repositories import kg_repo
from app.utils.job_helpers import (
    activate_graph_entities_by_job,
    cleanup_pending_by_job,
    update_job_progress,
)
from app.workflows.common.result import WorkflowResult
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.kg.support import workflow_logger
from app.workflows.digest.unified.models import TopicAnchor, TopicAnchorSnapshot
from app.workflows.digest.unified.session import get_unified_build_session


def _new_runtime_job_id() -> int:
    return (uuid.uuid4().int % 2_000_000_000) + 1


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
            select(KnowledgeNode.id).where(
                KnowledgeNode.subject == subject,
                KnowledgeNode.status == "active",
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


def build_finalize_graph_node(
    *,
    trigger_curriculum_derive: Callable[..., Awaitable[None]],
):
    """Build the finalize node with an injected curriculum trigger."""

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
                curriculum_job_id = _new_runtime_job_id()
                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="completed",
                    curriculum_job_id=curriculum_job_id,
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
                    curriculum_job_id=curriculum_job_id,
                    topic_anchor_count=len(topic_snapshot.anchors),
                    resolved_node_count=resolved_node_count,
                    active_node_count=active_node_count,
                    active_edge_count=active_edge_count,
                )
                asyncio.create_task(
                    trigger_curriculum_derive(
                        subject=subject,
                        graph_job_id=job_id,
                        curriculum_job_id=curriculum_job_id,
                        impact_set=state.get("impact_set"),
                        build_session_id=build_session_id,
                    )
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


async def fail_node(state: KGDigestState) -> KGDigestState:
    """Clean up pending graph data and mark the job as failed."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            job_id = state["job_id"]
            error_message = state.get("error", "unknown_error")
            cleanup_pending_by_job(
                session,
                job_id=job_id,
                job_type="graph",
                subject=state["subject"],
            )
            if state.get("lock_acquired", False):
                kg_repo.release_subject_build_lock(session, state["subject"])

            kg_repo.update_digest_job(
                session,
                job_id,
                status="failed",
                error_message=error_message,
                current_step=_resolve_failure_step(error_message),
            )
            digest_logger.error(
                "kg_workflow_failed",
                error=error_message,
                lock_acquired=state.get("lock_acquired", False),
                chunk_count=len(state.get("chunk_ids", [])),
            )
            return state
        except Exception as exc:
            digest_logger.error("kg_workflow_fail_node_error", error=str(exc), exc_info=True)
            return state


def _resolve_failure_step(error_message: str) -> str:
    if error_message.startswith("prepare_failed:"):
        return "prepare_failed"
    if error_message.startswith("extract_failed:"):
        return "extract_failed"
    if error_message.startswith("cluster_failed:"):
        return "cluster_failed"
    if error_message.startswith("resolve_nodes_failed:"):
        return "resolve_nodes_failed"
    if error_message.startswith("resolve_edges_failed:"):
        return "resolve_edges_failed"
    if error_message.startswith("analyze_impact_failed:"):
        return "analyze_impact_failed"
    if error_message.startswith("finalize_failed:"):
        return "finalize_failed"
    if error_message == "lock_conflict":
        return "acquire_lock_failed"
    if error_message == "no_ready_digest_inputs":
        return "prepare_failed"
    return "failed"


async def trigger_curriculum_derive_safe(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    impact_set: object | None,
    build_session_id: str | None,
    run_curriculum_derive_workflow: Callable[..., Awaitable[WorkflowResult[object]]],
) -> None:
    """Run curriculum derive in the background."""

    try:
        result = await run_curriculum_derive_workflow(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
            impact_set=impact_set,
            build_session_id=build_session_id,
        )
        if result.failed:
            workflow_logger({"subject": subject, "job_id": graph_job_id, "file_ids": []}).error(
                "curriculum_derive_auto_trigger_failed_result",
                curriculum_job_id=curriculum_job_id,
                error=result.error.detail,
            )
    except Exception:
        workflow_logger({"subject": subject, "job_id": graph_job_id, "file_ids": []}).exception(
            "curriculum_derive_auto_trigger_failed",
            curriculum_job_id=curriculum_job_id,
        )
        workflow_logger({"subject": subject, "job_id": graph_job_id, "file_ids": []}).error(
            "curriculum_derive_auto_trigger_failed_traceback",
            error=traceback.format_exc()[-500:],
        )


__all__ = [
    "build_finalize_graph_node",
    "fail_node",
    "trigger_curriculum_derive_safe",
]
