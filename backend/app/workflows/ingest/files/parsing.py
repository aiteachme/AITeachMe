"""File parsing workflow entrypoints."""

from __future__ import annotations

import asyncio

import structlog
from sqlmodel import Session

from app.shared.infra.exceptions import InvalidRawFileStateError
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import update_raw_file
from app.utils.presenters import require_id, require_uid
from app.workflows.ingest import run_parse_file_workflow
from app.workflows.ingest.fast_parse.lib.lifecycle import (
    dispatch_enhancement_if_needed,
    mark_parse_workflow_failed,
)
from app.workflows.ingest.files.catalog import get_subject_files_or_raise, get_user_files_or_raise
from app.workflows.ingest.common.parsing.defaults import DEFAULT_PARSE_CONCURRENCY

logger = structlog.get_logger()


def _start_parse_for_files(
    session: Session,
    *,
    owner_user_id: str,
    subject: str | None,
    file_ids: list[int],
) -> list[RawFile]:
    raw_files = (
        get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
        if subject
        else get_user_files_or_raise(session, owner_user_id=owner_user_id, file_ids=file_ids)
    )
    logger.info(
        "file_parse_state_transition_requested",
        subject=subject or "",
        user_id=owner_user_id,
        requested_file_ids=file_ids,
        raw_file_states=[
            {
                "file_id": require_id(item.id, "RawFile.id"),
                "file_uid": require_uid(item.uid, "RawFile.uid"),
                "status": item.status,
                "markdown_ready": bool(item.markdown_path),
                "filename": item.filename,
            }
            for item in raw_files
        ],
    )

    for raw_file in raw_files:
        raw_file_id = require_id(raw_file.id, "RawFile.id")
        raw_file_uid = require_uid(raw_file.uid, "RawFile.uid")
        if raw_file.status != TaskStatus.PENDING.value:
            raise InvalidRawFileStateError(raw_file_uid or raw_file_id, raw_file.status, TaskStatus.PENDING.value)

        update_raw_file(
            session,
            raw_file,
            status=TaskStatus.PROCESSING.value,
            error_message=None,
            ingest_status=IngestStatus.CLASSIFYING.value,
            digest_current_step="ingest.parse.queued",
        )

    logger.info(
        "file_parse_state_transition_completed",
        subject=subject or "",
        user_id=owner_user_id,
        accepted_file_ids=file_ids,
        accepted_file_uids=[require_uid(item.uid, "RawFile.uid") for item in raw_files],
        accepted_count=len(file_ids),
    )
    return (
        get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
        if subject
        else get_user_files_or_raise(session, owner_user_id=owner_user_id, file_ids=file_ids)
    )


async def run_parse_files_background(
    *,
    user_id: str,
    file_ids: list[int],
    subject: str | None = None,
    background_task_registry=None,
) -> None:
    concurrency = max(DEFAULT_PARSE_CONCURRENCY, 1)
    batch_logger = logger.bind(subject=subject or "", user_id=user_id, file_ids=file_ids)
    batch_logger.info(
        "file_parse_background_started",
        file_count=len(file_ids),
        concurrency=concurrency,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def _run_one(file_id: int) -> None:
        async with semaphore:
            batch_logger.info("file_parse_background_dispatch", file_id=file_id)
            try:
                result = await run_parse_file_workflow(
                    user_id=user_id,
                    file_id=file_id,
                    subject=subject or "",
                )
            except asyncio.CancelledError:
                batch_logger.warning("file_parse_background_dispatch_cancelled", file_id=file_id)
                raise
            except Exception as exc:
                mark_parse_workflow_failed(
                    user_id=user_id,
                    file_id=file_id,
                    error=str(exc),
                    step="ingest.unhandled_error",
                    subject=subject or "",
                )
                batch_logger.exception(
                    "file_parse_background_crashed",
                    file_id=file_id,
                    error=str(exc),
                )
                return

            if result.failed:
                if result.error and result.error.code == "workflow_execution_failed":
                    mark_parse_workflow_failed(
                        user_id=user_id,
                        file_id=file_id,
                        error=result.error.detail,
                        step="ingest.unhandled_error",
                        subject=subject or "",
                    )
                error_metadata = result.error.metadata if result.error else {}
                batch_logger.warning(
                    "file_parse_background_failed",
                    file_id=file_id,
                    error=result.error.detail,
                    filename=error_metadata.get("filename"),
                    filetype=error_metadata.get("filetype"),
                    parse_mode=error_metadata.get("parse_mode"),
                    parser_chain=error_metadata.get("parser_chain"),
                )
                return

            final_state = result.require_value()
            dispatched_enhance = dispatch_enhancement_if_needed(
                final_state,
                background_task_registry=background_task_registry,
            )
            if dispatched_enhance:
                batch_logger.info("file_parse_background_enhance_dispatched", file_id=file_id)

    try:
        await asyncio.gather(*(_run_one(file_id) for file_id in file_ids))
        batch_logger.info("file_parse_background_completed")
    except asyncio.CancelledError:
        batch_logger.warning("file_parse_background_cancelled")
        raise


__all__ = ["_start_parse_for_files", "run_parse_files_background"]
