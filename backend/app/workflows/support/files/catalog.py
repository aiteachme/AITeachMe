"""File catalog use cases."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

from sqlmodel import Session

from app.shared.infra.exceptions import RawFileNotFoundError
from app.shared.infra.storage import get_content_store, run_store_sync
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import (
    get_raw_file_by_id,
    list_raw_files_by_ids,
    list_raw_files_by_subject,
    list_raw_files_by_uids,
)
from app.schemas.files import FileAssetItem, FileRecord, FilesData
from app.utils.path_helpers import (
    build_asset_dir,
    build_asset_name_prefix,
    get_data_dir,
    list_asset_files,
)
from app.utils.presenters import require_id, require_uid


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


def _build_asset_name_prefix_for_raw_file(raw_file: RawFile) -> str:
    return build_asset_name_prefix(
        filename=raw_file.filename,
        file_uid=require_uid(raw_file.uid, "RawFile.uid"),
        file_id=require_id(raw_file.id, "RawFile.id"),
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


def _build_runtime_asset_url(path_value: str | Path | None) -> str | None:
    if not path_value:
        return None

    asset_path = Path(path_value).resolve()
    data_dir = get_data_dir().resolve()
    try:
        relative_path = asset_path.relative_to(data_dir)
    except ValueError:
        return None

    encoded_parts = [quote(part) for part in relative_path.parts]
    return f"/_assets/{'/'.join(encoded_parts)}"


def _build_asset_items(*, asset_dir_value: str | None, asset_name_prefix: str) -> list[FileAssetItem]:
    assets: list[FileAssetItem] = []
    for path in list_asset_files(asset_dir_value, asset_name_prefix=asset_name_prefix):
        asset_url = _build_runtime_asset_url(path)
        if not asset_url:
            continue

        assets.append(
            FileAssetItem(
                name=path.name,
                url=asset_url,
                mime_type=mimetypes.guess_type(path.name)[0],
            )
        )
    return assets


def _read_markdown(markdown_path_value: str | None) -> str:
    if not markdown_path_value:
        return ""

    cs = get_content_store()
    return run_store_sync(cs.read_text, markdown_path_value, default="") or ""


def build_file_record(raw_file: RawFile) -> FileRecord:
    file_uid = require_uid(raw_file.uid, "RawFile.uid")
    markdown_ready = _is_markdown_ready(raw_file)
    asset_name_prefix = _build_asset_name_prefix_for_raw_file(raw_file)
    asset_dir_value = raw_file.asset_dir
    if not asset_dir_value and raw_file.id is not None:
        asset_dir_value = str(build_asset_dir(raw_file.subject, raw_file.id))
    assets = _build_asset_items(
        asset_dir_value=asset_dir_value,
        asset_name_prefix=asset_name_prefix,
    )
    asset_base_url = _build_runtime_asset_url(asset_dir_value) if assets else None
    return FileRecord(
        uid=file_uid,
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
        markdown_content=_read_markdown(raw_file.markdown_path),
        asset_base_url=asset_base_url,
        assets=assets,
        classification_json=raw_file.classification_json,
        quality_score=raw_file.quality_score,
        digest_current_step=raw_file.digest_current_step,
        parse_metadata_json=raw_file.parse_metadata_json or raw_file.parse_metadata,
        latest_updated_at=raw_file.updated_at,
        created_at=raw_file.created_at,
    )


def get_subject_file_or_raise(session: Session, *, subject: str, file_id: int) -> RawFile:
    raw_file = get_raw_file_by_id(session, file_id)
    if raw_file is None or raw_file.subject != subject:
        raise RawFileNotFoundError(file_id)
    return raw_file


def get_subject_files_or_raise(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
) -> list[RawFile]:
    items = list_raw_files_by_ids(session, subject, file_ids)
    found_ids = {require_id(item.id, "RawFile.id") for item in items}
    missing = [file_id for file_id in file_ids if file_id not in found_ids]
    if missing:
        raise RawFileNotFoundError(missing[0])

    order = {file_id: index for index, file_id in enumerate(file_ids)}
    return sorted(items, key=lambda item: order[require_id(item.id, "RawFile.id")])


def get_subject_files_by_uid_or_raise(
    session: Session,
    *,
    subject: str,
    file_uids: list[str],
) -> list[RawFile]:
    items = list_raw_files_by_uids(session, subject, file_uids)
    found_uids = {require_uid(item.uid, "RawFile.uid") for item in items}
    missing = [file_uid for file_uid in file_uids if file_uid not in found_uids]
    if missing:
        raise RawFileNotFoundError(missing[0])

    order = {file_uid: index for index, file_uid in enumerate(file_uids)}
    return sorted(items, key=lambda item: order[require_uid(item.uid, "RawFile.uid")])


def list_subject_files(
    session: Session,
    *,
    subject: str,
) -> FilesData:
    raw_files, total = list_raw_files_by_subject(
        session,
        subject,
        limit=1000,
        offset=0,
        status=None,
    )
    records = [build_file_record(item) for item in raw_files]
    return FilesData(
        subject=subject,
        total=total,
        ready_count=sum(1 for item in records if item.markdown_ready),
        processing_count=sum(
            1 for item in records if not item.markdown_ready and item.status != TaskStatus.FAILED.value
        ),
        failed_count=sum(1 for item in records if item.status == TaskStatus.FAILED.value),
        items=records,
    )


__all__ = [
    "build_file_record",
    "get_subject_file_or_raise",
    "get_subject_files_by_uid_or_raise",
    "get_subject_files_or_raise",
    "list_subject_files",
]
