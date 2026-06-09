"""Parse dispatch entrypoints for ingested RawFiles."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

import structlog
from sqlmodel import Session

from app.shared.infra.exceptions import InvalidRawFileStateError
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import update_raw_file
from app.utils.presenters import require_id
from app.workflows.ingest.intake.catalog import get_course_files_or_raise, get_user_files_or_raise
from app.workflows.ingest.parsing.lib.defaults import DEFAULT_PARSE_CONCURRENCY

logger = structlog.get_logger()

_RETRIEVAL_READY_INGEST_STATUSES = {
    IngestStatus.FAST_PARSED.value,
    IngestStatus.ENHANCING.value,
    IngestStatus.READY_FOR_DIGEST.value,
    IngestStatus.ENHANCE_FAILED.value,
}


def _normalize_file_ids(file_ids: Iterable[str]) -> list[str]:
    return [
        file_id
        for file_id in dict.fromkeys(str(item or "").strip() for item in file_ids)
        if file_id
    ]


def ready_file_ids_for_course_indexing(raw_files: Iterable[RawFile]) -> list[str]:
    """Return parsed files that can be materialized into a course vector index."""

    ready_file_ids: list[str] = []
    for raw_file in raw_files:
        file_id = str(raw_file.id or "").strip()
        if not file_id:
            continue
        if raw_file.status != TaskStatus.COMPLETED.value:
            continue
        if raw_file.ingest_status not in _RETRIEVAL_READY_INGEST_STATUSES:
            continue
        if not (str(raw_file.parsed_markdown or "").strip() or str(raw_file.markdown_path or "").strip()):
            continue
        ready_file_ids.append(file_id)
    return _normalize_file_ids(ready_file_ids)


async def run_index_course_files_background(
    *,
    user_id: str,
    course_id: str | None,
    file_ids: list[str],
    reason: str,
) -> None:
    normalized_course_id = str(course_id or "").strip()
    normalized_file_ids = _normalize_file_ids(file_ids)
    if not normalized_course_id or not normalized_file_ids:
        return

    index_logger = logger.bind(
        course_id=normalized_course_id,
        user_id=str(user_id or ""),
        file_ids=normalized_file_ids,
        reason=reason,
    )
    index_logger.info("course_file_index_background_started", file_count=len(normalized_file_ids))
    try:
        from app.workflows.digest.common.indexing import index_course_files_for_retrieval

        materialized = await index_course_files_for_retrieval(
            course_id=normalized_course_id,
            file_ids=normalized_file_ids,
            reason=reason,
        )
        index_logger.info(
            "course_file_index_background_completed",
            file_count=len(normalized_file_ids),
            indexed=materialized is not None,
            chunk_count=len(getattr(materialized, "chunk_ids", []) or []),
        )
    except asyncio.CancelledError:
        index_logger.warning("course_file_index_background_cancelled")
        raise
    except Exception as exc:
        index_logger.warning("course_file_index_background_failed", error=str(exc))


def spawn_index_course_files_background(
    background_task_registry,
    *,
    user_id: str,
    course_id: str | None,
    file_ids: list[str],
    reason: str,
) -> list[str]:
    normalized_course_id = str(course_id or "").strip()
    normalized_file_ids = _normalize_file_ids(file_ids)
    if not normalized_course_id or not normalized_file_ids:
        return []
    if background_task_registry is None:
        logger.warning(
            "course_file_index_background_registry_missing",
            course_id=normalized_course_id,
            user_id=str(user_id or ""),
            file_ids=normalized_file_ids,
            reason=reason,
        )
        return []

    coroutine = run_index_course_files_background(
        user_id=user_id,
        course_id=normalized_course_id,
        file_ids=normalized_file_ids,
        reason=reason,
    )
    try:
        background_task_registry.spawn(
            coroutine,
            kind="files.index",
            course_id=normalized_course_id,
            name=f"files.index:{normalized_course_id}",
            dedupe_key=f"files.index:{normalized_course_id}:{':'.join(sorted(normalized_file_ids))}",
        )
    except Exception:
        coroutine.close()
        raise
    return normalized_file_ids


async def _index_file_after_parse(
    *,
    user_id: str,
    course_id: str | None,
    file_id: str,
    reason: str,
) -> None:
    await run_index_course_files_background(
        user_id=user_id,
        course_id=course_id,
        file_ids=[file_id],
        reason=reason,
    )


def _start_parse_for_files(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str | None,
    file_ids: list[str],
) -> list[RawFile]:
    raw_files = (
        get_course_files_or_raise(session, course_id=course_id, file_ids=file_ids)
        if course_id
        else get_user_files_or_raise(session, owner_user_id=owner_user_id, file_ids=file_ids)
    )
    logger.info(
        "file_parse_state_transition_requested",
        course_id=course_id or "",
        user_id=owner_user_id,
        requested_file_ids=file_ids,
        raw_file_states=[
            {
                "file_id": require_id(item.id, "RawFile.id"),
                "status": item.status,
                "markdown_ready": bool(item.markdown_path),
                "filename": item.filename,
            }
            for item in raw_files
        ],
    )

    for raw_file in raw_files:
        file_id = require_id(raw_file.id, "RawFile.id")
        if raw_file.status != TaskStatus.PENDING.value:
            raise InvalidRawFileStateError(file_id, raw_file.status, TaskStatus.PENDING.value)

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
        course_id=course_id or "",
        user_id=owner_user_id,
        accepted_file_ids=file_ids,
        accepted_count=len(file_ids),
    )
    return (
        get_course_files_or_raise(session, course_id=course_id, file_ids=file_ids)
        if course_id
        else get_user_files_or_raise(session, owner_user_id=owner_user_id, file_ids=file_ids)
    )


async def run_parse_files_background(
    *,
    user_id: str,
    file_ids: list[str],
    course_id: str | None = None,
    background_task_registry=None,
) -> None:
    concurrency = max(DEFAULT_PARSE_CONCURRENCY, 1)
    batch_logger = logger.bind(course_id=course_id or "", user_id=user_id, file_ids=file_ids)
    batch_logger.info(
        "file_parse_background_started",
        file_count=len(file_ids),
        concurrency=concurrency,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def _run_one(file_id: str) -> None:
        async with semaphore:
            batch_logger.info("file_parse_background_dispatch", file_id=file_id)
            try:
                from app.workflows.ingest import run_parse_file_workflow

                result = await run_parse_file_workflow(
                    user_id=user_id,
                    file_id=file_id,
                    course_id=course_id or "",
                )
            except asyncio.CancelledError:
                batch_logger.warning("file_parse_background_dispatch_cancelled", file_id=file_id)
                raise
            except Exception as exc:
                from app.workflows.ingest.parsing.lib.lifecycle import mark_parse_workflow_failed

                mark_parse_workflow_failed(
                    user_id=user_id,
                    file_id=file_id,
                    error=str(exc),
                    step="ingest.unhandled_error",
                    course_id=course_id or "",
                )
                batch_logger.exception(
                    "file_parse_background_crashed",
                    file_id=file_id,
                    error=str(exc),
                )
                return

            if result.failed:
                if result.error and result.error.code == "workflow_execution_failed":
                    from app.workflows.ingest.parsing.lib.lifecycle import mark_parse_workflow_failed

                    mark_parse_workflow_failed(
                        user_id=user_id,
                        file_id=file_id,
                        error=result.error.detail,
                        step="ingest.unhandled_error",
                        course_id=course_id or "",
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
            await _index_file_after_parse(
                user_id=user_id,
                course_id=course_id,
                file_id=file_id,
                reason=(
                    "ingest.parse.completed_pre_enhance"
                    if bool(final_state.get("needs_enhance"))
                    else "ingest.parse.completed"
                ),
            )
            from app.workflows.ingest.parsing.lib.lifecycle import dispatch_enhancement_if_needed

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


__all__ = [
    "_start_parse_for_files",
    "ready_file_ids_for_course_indexing",
    "run_index_course_files_background",
    "run_parse_files_background",
    "spawn_index_course_files_background",
]
