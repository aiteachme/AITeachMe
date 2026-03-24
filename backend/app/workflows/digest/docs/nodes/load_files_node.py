"""Load docs lane inputs from the unified build session."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy
from app.workflows.digest.unified.session import get_unified_build_session

logger = structlog.get_logger()


def build_load_files_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the docs input loader."""

    del strategy

    async def load_files_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="load_files")
        build_session_id = state.get("build_session_id", "")
        if not build_session_id:
            return {"error": "Missing unified build session id for docs lane."}

        session = get_unified_build_session(build_session_id)
        shared_inputs = session.shared_inputs
        raw_chunks = [
            {
                "file_id": source_packet.file_id,
                "content": source_packet.normalized_content,
                "source_filename": source_packet.filename,
                "filetype": source_packet.filetype,
            }
            for source_packet in shared_inputs.source_packets
        ]
        load_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_loading_from_unified_session_completed",
            build_session_id=build_session_id,
            file_count=len(raw_chunks),
            section_count=len(shared_inputs.section_packets),
            load_ms=load_ms,
        )
        return {
            "raw_chunks": raw_chunks,
            "shared_inputs": shared_inputs,
            "load_ms": load_ms,
        }

    return load_files_node
