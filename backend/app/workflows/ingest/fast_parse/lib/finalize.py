"""Finalize nodes for ingest workflows.

这里负责把 graph 中的临时解析结果持久化成 ``RawFile`` 可消费状态。
Phase 2 增强任务派发属于 graph 外的生命周期收口，不在节点里处理。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.shared.infra.database import managed_session
from app.shared.infra.storage import get_content_store
from app.models import IngestStatus, TaskStatus
from app.repositories.files_repo import get_raw_file_by_id, replace_raw_file_assets, update_raw_file
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.ingest.fast_parse.lib.common import workflow_logger
from app.workflows.ingest.fast_parse.lib.runtime_helpers import _build_asset_rows
from app.workflows.ingest.fast_parse.state import IngestParseState


def _cleanup_temp_dir(state: IngestParseState) -> None:
    temp_dir = state.get("temp_dir")
    if not temp_dir:
        return
    shutil.rmtree(temp_dir, ignore_errors=True)


def build_finalize_success_node(
    *,
    context: WorkflowContext,
):
    """Finalize Phase 1, publish assets, and optionally dispatch Phase 2."""

    async def finalize_success_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        cs = get_content_store()
        try:
            local_markdown_path = Path(state["local_markdown_path"])
            local_asset_dir = Path(state["local_asset_dir"])
            parsed_markdown = state.get("parsed_markdown")
            if parsed_markdown is None and local_markdown_path.exists():
                parsed_markdown = local_markdown_path.read_text(encoding="utf-8")
            if parsed_markdown is None:
                return {
                    **state,
                    "error": f"parsed_markdown_missing:{state['file_id']}",
                }

            await cs.write_text(state["record_markdown_path"], parsed_markdown)
            await cs.upload_dir(local_asset_dir, state["asset_upload_prefix"])

            asset_rows = _build_asset_rows(
                raw_file_id=state["file_id"],
                asset_dir=local_asset_dir,
                asset_storage_dir=state["asset_storage_dir"],
                storage_backend=state["storage_backend"],
            )
            needs_enhance = bool(state.get("needs_enhance", False))
            is_text_fast_path = bool(state.get("is_text_fast_path", False))
            if is_text_fast_path:
                final_ingest_status = IngestStatus.READY_FOR_DIGEST.value
                digest_current_step = "ingest.fast_path.completed"
            elif needs_enhance:
                final_ingest_status = IngestStatus.FAST_PARSED.value
                digest_current_step = "ingest.fast_parse.completed"
            else:
                final_ingest_status = IngestStatus.READY_FOR_DIGEST.value
                digest_current_step = "ingest.parse.completed"

            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is None or raw_file.user_id != state["user_id"]:
                    return {
                        **state,
                        "error": f"raw_file_not_found:{state['file_id']}",
                    }

                replace_raw_file_assets(session, raw_file_id=state["file_id"], assets=asset_rows)
                update_raw_file(
                    session,
                    raw_file,
                    parsed_markdown=parsed_markdown,
                    parser_used=state.get("parser_used"),
                    parse_metadata_json=state.get("parse_metadata") or "{}",
                    parse_error_message=None,
                    classification_json=state.get("classification_payload") or "{}",
                    quality_score=state.get("quality_score"),
                    image_count=len(asset_rows),
                    estimated_pages=state.get("estimated_pages"),
                    detected_language=state.get("detected_language"),
                    status=TaskStatus.COMPLETED.value,
                    ingest_status=final_ingest_status,
                    digest_current_step=digest_current_step,
                    size_bytes=state.get("file_size_bytes"),
                    checksum_sha256=state.get("content_hash"),
                    markdown_path=state["record_markdown_path"],
                    asset_dir=state["record_asset_dir"],
                )

            logger.info(
                "ingest_file_fast_parse_finalized",
                parser_used=state.get("parser_used"),
                markdown_chars=state.get("markdown_chars", 0),
                image_count=len(asset_rows),
                needs_enhance=needs_enhance,
                digest_current_step=digest_current_step,
            )
            return {
                **state,
                "image_count": len(asset_rows),
                "error": None,
            }
        except Exception as exc:
            logger.error("ingest_file_finalize_success_failed", error=str(exc), exc_info=True)
            return {
                **state,
                "error": f"finalize_success_failed: {exc}",
            }
        finally:
            _cleanup_temp_dir(state)

    return finalize_success_node


def build_finalize_failure_node(*, context: WorkflowContext):
    """Finalize a failed Phase 1 run and mark the raw file as failed."""

    async def finalize_failure_node(state: IngestParseState) -> IngestParseState:
        logger = workflow_logger(context, state)
        error_message = state.get("error", "unknown_error")
        try:
            with managed_session() as session:
                raw_file = get_raw_file_by_id(session, state["file_id"])
                if raw_file is not None and raw_file.user_id == state["user_id"]:
                    update_raw_file(
                        session,
                        raw_file,
                        parse_error_message=error_message,
                        status=TaskStatus.FAILED.value,
                        ingest_status=IngestStatus.FAILED.value,
                        digest_current_step="ingest.parse.failed",
                    )
        finally:
            _cleanup_temp_dir(state)

        logger.error("ingest_file_finalize_failed", error=error_message)
        return state

    return finalize_failure_node
