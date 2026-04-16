"""Knowledge graph prepare node."""

from __future__ import annotations

from app.shared.infra.database import managed_session
from app.utils.job_helpers import update_job_progress
from app.workflows.digest.common.materialize import materialize_shared_inputs
from app.workflows.digest.common.prepare import prepare_shared_inputs
from app.workflows.digest.knowledge_graph.state import KGDigestState
from app.workflows.digest.knowledge_graph.support import workflow_logger


async def prepare_node(state: KGDigestState) -> KGDigestState:
    """Prepare graph-owned shared inputs and canonical retrieval chunks."""

    digest_logger = workflow_logger(state)
    try:
        subject = state["subject"]
        file_ids = list(state.get("file_ids", []))
        shared_inputs = await prepare_shared_inputs(
            subject,
            file_ids,
            user_prompt=state.get("user_prompt"),
        )
        if not shared_inputs.source_packets or not shared_inputs.section_packets:
            return {**state, "error": "no_ready_digest_inputs"}

        materialized = await materialize_shared_inputs(
            subject=subject,
            shared_inputs=shared_inputs,
            build_session_id=state.get("build_session_id") or None,
        )
        chunk_ids = list(materialized.chunk_ids)
        if not chunk_ids:
            return {**state, "error": "no_ready_digest_inputs"}

        with managed_session() as session:
            update_job_progress(
                session,
                job_id=state["job_id"],
                job_type="graph",
                progress=10,
                current_step="prepare",
            )
        digest_logger.info(
            "kg_workflow_prepare_complete",
            build_session_id=materialized.build_session_id,
            document_count=len(materialized.document_ids),
            chunk_count=len(chunk_ids),
            source_file_ids=materialized.source_file_ids,
        )
        return {
            **state,
            "build_session_id": materialized.build_session_id,
            "shared_inputs": shared_inputs,
            "chunk_ids": chunk_ids,
            "chunk_uid_to_chunk_id": dict(materialized.chunk_uid_to_chunk_id),
            "chunk_id_to_chunk_uid": dict(materialized.chunk_id_to_chunk_uid),
        }
    except Exception as exc:
        digest_logger.error("kg_workflow_prepare_failed", error=str(exc), exc_info=True)
        return {**state, "error": f"prepare_failed: {exc}"}


__all__ = ["prepare_node"]
