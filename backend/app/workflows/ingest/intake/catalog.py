"""File catalog use cases."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from sqlmodel import Session

from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import (
    get_raw_file_by_id,
    get_raw_file_by_id_for_user,
    list_raw_files_by_ids,
    list_raw_files_by_ids_for_user,
    list_raw_files_by_course,
    list_raw_files_by_user,
    raw_file_belongs_to_course,
)
from app.schemas.files import FileRecord, FilesData
from app.shared.infra.exceptions import RawFileNotFoundError
from app.shared.infra.storage import get_content_store
from app.utils.presenters import require_id


_FILE_MARKDOWN_READ_TIMEOUT_SECONDS = 8.0


def _is_markdown_ready(raw_file: RawFile, *, markdown_content: str | None = None) -> bool:
    content = markdown_content if markdown_content is not None else raw_file.parsed_markdown
    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status
        in {
            IngestStatus.FAST_PARSED.value,
            IngestStatus.ENHANCING.value,
            IngestStatus.READY_FOR_DIGEST.value,
            IngestStatus.ENHANCE_FAILED.value,
        }
        and bool(str(content or "").strip())
    )


def _extract_parser_used(raw_file: RawFile) -> str | None:
    if raw_file.parser_used:
        return raw_file.parser_used

    parse_metadata = raw_file.parse_metadata_json or raw_file.parse_metadata
    if not parse_metadata:
        return None

    try:
        payload = json.loads(parse_metadata)
    except json.JSONDecodeError:
        return None

    parser_used = payload.get("parser_used")
    return str(parser_used) if parser_used else None


async def resolve_file_markdown_content(raw_file: RawFile) -> str:
    """Resolve one file's Markdown without putting object storage on list paths."""

    in_db = str(raw_file.markdown_content or "")
    if in_db.strip() or not raw_file.markdown_path:
        return in_db

    try:
        recovered = await asyncio.wait_for(
            get_content_store().read_text(raw_file.markdown_path, default=""),
            timeout=_FILE_MARKDOWN_READ_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return ""
    return str(recovered or "")


def build_file_record(
    raw_file: RawFile,
    *,
    include_content: bool = True,
    markdown_content: str | None = None,
) -> FileRecord:
    file_id = require_id(raw_file.id, "RawFile.id")
    resolved_markdown = (
        str(raw_file.markdown_content or "")
        if markdown_content is None
        else str(markdown_content)
    )
    markdown_ready = _is_markdown_ready(raw_file, markdown_content=resolved_markdown)
    asset_dir_value = raw_file.asset_dir
    asset_ready = bool((raw_file.image_count or 0) > 0)
    asset_base_url = f"/api/v1/files/assets/{quote(file_id)}/" if asset_dir_value else None
    return FileRecord(
        id=file_id,
        filename=raw_file.filename,
        filetype=raw_file.filetype,
        status=raw_file.status,
        ingest_status=raw_file.ingest_status,
        markdown_ready=markdown_ready,
        asset_ready=asset_ready,
        error_message=raw_file.error_message,
        file_size_bytes=raw_file.file_size_bytes,
        detected_language=raw_file.detected_language,
        estimated_pages=raw_file.estimated_pages,
        image_count=raw_file.image_count,
        parser_used=_extract_parser_used(raw_file),
        markdown_content=resolved_markdown if include_content else "",
        asset_base_url=asset_base_url,
        assets=[],
        classification_json=raw_file.classification_json,
        quality_score=raw_file.quality_score,
        digest_current_step=raw_file.digest_current_step,
        parse_metadata_json=raw_file.parse_metadata_json or raw_file.parse_metadata,
        latest_updated_at=raw_file.updated_at,
        created_at=raw_file.created_at,
    )


def _has_file_error(record: FileRecord) -> bool:
    return record.status == TaskStatus.FAILED.value or bool((record.error_message or "").strip())


def _count_file_states(records: list[FileRecord]) -> tuple[int, int, int]:
    ready_count = sum(1 for item in records if item.markdown_ready)
    failed_count = sum(1 for item in records if _has_file_error(item))
    processing_count = sum(
        1
        for item in records
        if not item.markdown_ready and not _has_file_error(item)
    )
    return ready_count, processing_count, failed_count


def get_course_file_or_raise(session: Session, *, course_id: str, file_id: str) -> RawFile:
    raw_file = get_raw_file_by_id(session, file_id)
    if raw_file is None or not raw_file_belongs_to_course(session, raw_file=raw_file, course_id=course_id):
        raise RawFileNotFoundError(file_id)
    return raw_file


def get_user_file_or_raise(session: Session, *, owner_user_id: str, file_id: str) -> RawFile:
    raw_file = get_raw_file_by_id_for_user(session, user_id=owner_user_id, file_id=file_id)
    if raw_file is None:
        raise RawFileNotFoundError(file_id)
    return raw_file


def get_user_files_or_raise(
    session: Session,
    *,
    owner_user_id: str,
    file_ids: list[str],
) -> list[RawFile]:
    items = list_raw_files_by_ids_for_user(session, user_id=owner_user_id, file_ids=file_ids)
    found_ids = {require_id(item.id, "RawFile.id") for item in items}
    missing = [file_id for file_id in file_ids if file_id not in found_ids]
    if missing:
        raise RawFileNotFoundError(missing[0])

    order = {file_id: index for index, file_id in enumerate(file_ids)}
    return sorted(items, key=lambda item: order[require_id(item.id, "RawFile.id")])


def get_course_files_or_raise(
    session: Session,
    *,
    course_id: str,
    file_ids: list[str],
) -> list[RawFile]:
    items = list_raw_files_by_ids(session, course_id, file_ids)
    found_ids = {require_id(item.id, "RawFile.id") for item in items}
    missing = [file_id for file_id in file_ids if file_id not in found_ids]
    if missing:
        raise RawFileNotFoundError(missing[0])

    order = {file_id: index for index, file_id in enumerate(file_ids)}
    return sorted(items, key=lambda item: order[require_id(item.id, "RawFile.id")])

def list_course_files(
    session: Session,
    *,
    course_id: str,
) -> FilesData:
    raw_files, total = list_raw_files_by_course(
        session,
        course_id,
        limit=1000,
        offset=0,
        status=None,
    )
    records = [build_file_record(item, include_content=False) for item in raw_files]
    ready_count, processing_count, failed_count = _count_file_states(records)
    return FilesData(
        course_id=course_id,
        total=total,
        ready_count=ready_count,
        processing_count=processing_count,
        failed_count=failed_count,
        items=records,
    )


def list_user_files(
    session: Session,
    *,
    owner_user_id: str,
    file_ids: list[str] | None = None,
) -> FilesData:
    raw_files, total = list_raw_files_by_user(
        session,
        user_id=owner_user_id,
        file_ids=file_ids,
        limit=1000,
        offset=0,
        status=None,
    )
    records = [build_file_record(item, include_content=False) for item in raw_files]
    ready_count, processing_count, failed_count = _count_file_states(records)
    return FilesData(
        course_id=None,
        total=total,
        ready_count=ready_count,
        processing_count=processing_count,
        failed_count=failed_count,
        items=records,
    )


__all__ = [
    "build_file_record",
    "get_course_file_or_raise",
    "get_course_files_or_raise",
    "get_user_file_or_raise",
    "get_user_files_or_raise",
    "list_course_files",
    "list_user_files",
    "resolve_file_markdown_content",
]
