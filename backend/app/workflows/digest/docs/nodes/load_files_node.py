"""Load docs lane inputs — standalone or from unified build session."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_load_files_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the docs input loader.

    Supports two modes:
    - **unified mode**: read shared inputs from the in-memory build session
      (``build_session_id`` present and registered).
    - **standalone mode**: prepare shared inputs directly from DB / storage.
    """

    del strategy

    async def load_files_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="load_files")

        # ------------------------------------------------------------------
        # 1. Try to load from unified session (backward-compatible)
        # ------------------------------------------------------------------
        build_session_id = state.get("build_session_id", "")
        shared_inputs = None

        if build_session_id:
            try:
                from app.workflows.digest.unified.session import get_unified_build_session

                session = get_unified_build_session(build_session_id)
                shared_inputs = session.shared_inputs
                node_logger.info(
                    "docgen_loading_from_unified_session",
                    build_session_id=build_session_id,
                )
            except KeyError:
                node_logger.info(
                    "docgen_unified_session_not_found_falling_back",
                    build_session_id=build_session_id,
                )

        # ------------------------------------------------------------------
        # 2. Standalone mode — prepare shared inputs directly
        # ------------------------------------------------------------------
        if shared_inputs is None:
            # Check if already passed via state (e.g. from runtime preparation)
            shared_inputs = state.get("shared_inputs")

        if shared_inputs is None:
            from app.workflows.digest.shared.prepare import prepare_shared_inputs

            subject = state["subject"]
            file_ids = state.get("file_ids", [])
            if not file_ids:
                return {"error": "No file_ids provided for standalone docs lane."}
            shared_inputs = await prepare_shared_inputs(
                subject,
                file_ids,
                user_prompt=state.get("user_prompt"),
            )

        if not shared_inputs.source_packets:
            return {"error": "No source packets found — nothing to process."}

        # ------------------------------------------------------------------
        # 3. Build raw chunks from shared inputs
        # ------------------------------------------------------------------
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
            "docgen_loading_completed",
            build_session_id=build_session_id or "(standalone)",
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
