"""Knowledge graph fail node."""

from __future__ import annotations

from app.shared.infra.database import managed_session
from app.repositories import kg_repo
from app.utils.job_helpers import cleanup_pending_by_job
from app.workflows.digest.knowledge_graph.state import KGDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger


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


__all__ = ["fail_node"]

