"""Knowledge graph acquire-lock node."""

from __future__ import annotations

from app.shared.infra.database import managed_session
from app.repositories.knowledge import kg_repo
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.knowledge_graph.state import KGDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger


async def acquire_lock_node(state: KGDigestState) -> KGDigestState:
    """Acquire a subject-scoped graph build lock."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        digest_logger.info("kg_workflow_acquire_lock_started")
        acquired = kg_repo.acquire_subject_build_lock(
            session,
            state["subject"],
            state["job_id"],
        )
        if not acquired:
            digest_logger.warning("kg_workflow_lock_conflict")
            return {**state, "lock_acquired": False, "error": "lock_conflict"}

        update_job_progress(
            session,
            job_id=state["job_id"],
            job_type="graph",
            progress=5,
            current_step="acquire_lock",
        )
        kg_repo.update_digest_job(session, state["job_id"], status="processing")
        digest_logger.info("kg_workflow_acquire_lock_completed")
        return {**state, "lock_acquired": True}


__all__ = ["acquire_lock_node"]
