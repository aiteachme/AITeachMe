"""Finalize nodes for ingest workflows."""

from __future__ import annotations

from app.core.database import managed_session
from app.models import IngestStatus, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, update_raw_file
from app.workflows.common.context import WorkflowContext
from app.workflows.ingest.nodes.common import workflow_logger
from app.workflows.ingest.events import IngestFileParseFailedEvent, IngestFileReadyForDigestEvent
from app.workflows.ingest.state import IngestParseState


def build_finalize_success_node(*, context: WorkflowContext):
    async def finalize_success_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        try:
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.subject != state["subject"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }
                update_raw_file(
                    session,
                    raw_file,
                    markdown_path=state["markdown_path"],
                    asset_dir=state["asset_dir"],
                    status=TaskStatus.COMPLETED.value,
                    error_message=None,
                    content_hash=state.get("content_hash"),
                    file_size_bytes=state.get("file_size_bytes"),
                    estimated_pages=state.get("estimated_pages"),
                    detected_language=state.get("detected_language"),
                    classification_result=state.get("classification_payload"),
                    parse_metadata=state.get("parse_metadata"),
                    image_count=state.get("image_count"),
                    ingest_status=IngestStatus.READY_FOR_DIGEST.value,
                )
            await context.event_bus.publish(
                IngestFileReadyForDigestEvent(
                    subject=state["subject"],
                    file_id=state["file_id"],
                )
            )
            logger.info(
                "ingest_file_finalize_success",
                parser_used=state.get("parser_used"),
                markdown_chars=state.get("markdown_chars", 0),
                image_count=state.get("image_count", 0),
            )
            return {
                **state,
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_file_finalize_success_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"finalize_success_failed: {exc}",
            }

    return finalize_success_node


def build_finalize_failure_node(*, context: WorkflowContext):
    async def finalize_failure_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        error_message = state.get("error", "unknown_error")
        with managed_session() as session:
            raw_file = get_raw_file_by_id(session, state["file_id"])
            if raw_file is not None and raw_file.subject == state["subject"]:
                update_raw_file(
                    session,
                    raw_file,
                    asset_dir=state.get("asset_dir"),
                    status=TaskStatus.FAILED.value,
                    error_message=error_message,
                    ingest_status=IngestStatus.FAILED.value,
                )
        await context.event_bus.publish(
            IngestFileParseFailedEvent(
                subject=state["subject"],
                file_id=state["file_id"],
                error_message=error_message,
            )
        )
        logger.error("ingest_file_finalize_failed", error=error_message)
        return state

    return finalize_failure_node
