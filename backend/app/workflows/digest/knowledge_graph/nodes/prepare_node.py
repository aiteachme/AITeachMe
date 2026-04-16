"""Knowledge graph prepare node."""

from __future__ import annotations

from app.shared.infra.database import managed_session
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.knowledge_graph.state import KnowledgeDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger
from app.workflows.digest.unified.session import get_unified_build_session


async def prepare_node(state: KnowledgeDigestState) -> KnowledgeDigestState:
    """Load canonical chunk ids from the unified build session."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            build_session_id = state.get("build_session_id", "")
            if not build_session_id:
                return {**state, "error": "missing_build_session_id"}

            unified_session = get_unified_build_session(build_session_id)
            materialized = unified_session.materialized
            chunk_ids = list(materialized.chunk_ids)
            if not chunk_ids:
                return {**state, "error": "no_ready_digest_inputs"}

            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=10,
                current_step="prepare",
            )
            digest_logger.info(
                "knowledge_workflow_prepare_complete",
                build_session_id=build_session_id,
                document_count=len(materialized.document_ids),
                chunk_count=len(chunk_ids),
                source_file_ids=materialized.source_file_ids,
            )
            return {
                **state,
                "shared_inputs": unified_session.shared_inputs,
                "chunk_ids": chunk_ids,
                "chunk_uid_to_chunk_id": dict(materialized.chunk_uid_to_chunk_id),
                "chunk_id_to_chunk_uid": dict(materialized.chunk_id_to_chunk_uid),
            }
        except Exception as exc:
            digest_logger.error("knowledge_workflow_prepare_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"prepare_failed: {exc}"}


__all__ = ["prepare_node"]

