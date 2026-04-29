"""File catalog use cases."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

from sqlmodel import Session

from app.shared.infra.exceptions import RawFileNotFoundError
from app.shared.infra.storage import (
    get_content_store,
    run_store_sync,
)
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import (
    get_raw_file_by_id,
    list_raw_files_by_ids,
    list_raw_files_by_ids_for_user,
    list_raw_files_by_course,
    list_raw_files_by_user,
    raw_file_belongs_to_course,
)
from app.schemas.files import FileAssetItem, FileRecord, FilesData
from app.utils.presenters import require_id


def _is_markdown_ready(raw_file: RawFile) -> bool:
    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status
        in {
            IngestStatus.FAST_PARSED.value,
            IngestStatus.ENHANCING.value,
            IngestStatus.READY_FOR_DIGEST.value,
            IngestStatus.ENHANCE_FAILED.value,
        }
        and bool((raw_file.parsed_markdown or "").strip())
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


def _quote_path_parts(path_value: str) -> str:
    return "/".join(quote(part) for part in Path(path_value).parts if part)


def _build_runtime_asset_url(*, file_id: str, asset_relative_path: str | None) -> str | None:
    if not asset_relative_path:
        return None

    return f"/api/v1/files/assets/{quote(file_id)}/{_quote_path_parts(asset_relative_path)}"


def _build_asset_items(
    *,
    file_id: str,
    asset_dir_value: str | None,
) -> list[FileAssetItem]:
    if not asset_dir_value:
        return []

    cs = get_content_store()
    prefix = asset_dir_value.rstrip("/") + "/"
    keys = run_store_sync(cs.list_prefix, prefix, default=[]) or []
    assets: list[FileAssetItem] = []
    for key in keys:
        relative_path = _to_file_relative_storage_path(asset_dir_value=asset_dir_value, storage_key=key)
        asset_url = _build_runtime_asset_url(file_id=file_id, asset_relative_path=relative_path)
        if not asset_url:
            continue

        assets.append(
            FileAssetItem(
                name=Path(key).name,
                url=asset_url,
                mime_type=mimetypes.guess_type(key)[0],
            )
        )
    return assets


def _to_file_relative_storage_path(*, asset_dir_value: str | None, storage_key: str) -> str | None:
    if not asset_dir_value or not storage_key:
        return None
    prefix = asset_dir_value.rstrip("/") + "/"
    if not storage_key.startswith(prefix):
        return None
    relative = storage_key[len(prefix):].lstrip("/\\")
    return relative or None


def _read_markdown(markdown_path_value: str | None, *, markdown_content: str | None = None) -> str:
    in_db = str(markdown_content or "").strip()
    if in_db:
        return in_db

    if not markdown_path_value:
        return ""

    cs = get_content_store()
    return run_store_sync(cs.read_text, markdown_path_value, default="") or ""


def build_file_record(raw_file: RawFile) -> FileRecord:
    file_id = require_id(raw_file.id, "RawFile.id")
    markdown_ready = _is_markdown_ready(raw_file)
    asset_dir_value = raw_file.asset_dir
    if not asset_dir_value:
        scope = get_content_store().user_file_scope(user_id=raw_file.user_id or "local")
        asset_dir_value = scope.asset_prefix(file_id=file_id, filename=raw_file.filename).rstrip("/")
    assets = _build_asset_items(
        file_id=file_id,
        asset_dir_value=asset_dir_value,
    )
    asset_base_url = f"/api/v1/files/assets/{quote(file_id)}/" if assets else None
    return FileRecord(
        id=file_id,
        filename=raw_file.filename,
        filetype=raw_file.filetype,
        status=raw_file.status,
        ingest_status=raw_file.ingest_status,
        markdown_ready=markdown_ready,
        asset_ready=bool(assets),
        error_message=raw_file.error_message,
        file_size_bytes=raw_file.file_size_bytes,
        detected_language=raw_file.detected_language,
        estimated_pages=raw_file.estimated_pages,
        image_count=raw_file.image_count,
        parser_used=_extract_parser_used(raw_file),
        markdown_content=_read_markdown(
            raw_file.markdown_path,
            markdown_content=raw_file.markdown_content,
        ),
        asset_base_url=asset_base_url,
        assets=assets,
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
    records = [build_file_record(item) for item in raw_files]
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
    records = [build_file_record(item) for item in raw_files]
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
    "get_user_files_or_raise",
    "list_course_files",
    "list_user_files",
]
