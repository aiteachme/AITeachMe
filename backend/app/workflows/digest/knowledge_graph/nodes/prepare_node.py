"""Knowledge graph prepare node."""

from __future__ import annotations

from app.shared.infra.database import managed_session
import app.repositories.knowledge.knowledge_repo as knowledge_repo
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.knowledge_graph.state import KnowledgeDigestState
from app.workflows.digest.knowledge_graph.lib.support import workflow_logger


async def prepare_node(state: KnowledgeDigestState) -> KnowledgeDigestState:
    """Load canonical chunk ids for the current graph build."""

    with managed_session() as session:
        digest_logger = workflow_logger(state)
        try:
            build_session_id = state.get("build_session_id", "")
            if build_session_id:
                chunks = knowledge_repo.get_chunks_by_build_session(session, build_session_id)
            else:
                chunks = knowledge_repo.get_chunks_by_source_file_ids(
                    session,
                    subject=state["subject"],
                    source_file_ids=state.get("file_ids", []),
                )
            chunks = [chunk for chunk in chunks if chunk.id is not None and chunk.is_active]
            chunk_ids = [int(chunk.id) for chunk in chunks]
            if not chunk_ids:
                return {**state, "error": "no_ready_digest_inputs"}
            chunk_uid_to_chunk_id = {
                chunk.digest_chunk_uid: int(chunk.id)
                for chunk in chunks
                if chunk.digest_chunk_uid and chunk.id is not None
            }
            chunk_id_to_chunk_uid = {
                int(chunk.id): chunk.digest_chunk_uid
                for chunk in chunks
                if chunk.digest_chunk_uid and chunk.id is not None
            }

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
                chunk_count=len(chunk_ids),
                source_file_ids=state.get("file_ids", []),
            )
            return {
                **state,
                "chunk_ids": chunk_ids,
                "chunk_uid_to_chunk_id": chunk_uid_to_chunk_id,
                "chunk_id_to_chunk_uid": chunk_id_to_chunk_uid,
            }
        except Exception as exc:
            digest_logger.error("knowledge_workflow_prepare_failed", error=str(exc), exc_info=True)
            return {**state, "error": f"prepare_failed: {exc}"}


__all__ = ["prepare_node"]
