"""File service layer."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import shutil
import uuid
from pathlib import Path
from urllib.parse import quote

import structlog
from fastapi import UploadFile
from sqlmodel import Session

from app.core.config import get_settings
from app.core.exceptions import (
    FileParseError,
    FileTooLargeError,
    InvalidRawFileStateError,
    RawFileNotFoundError,
    SubjectRegistryNotFoundError,
)
from app.models import IngestStatus, RawFile, RawFileAsset, Subject, TaskStatus
from app.repositories.files_repo import (
    create_raw_file,
    delete_raw_file,
    get_raw_file_by_id,
    list_assets_by_raw_file_id,
    list_raw_files_by_ids,
    list_raw_files_by_subject,
    list_raw_files_by_uids,
    replace_raw_file_assets,
    update_raw_file,
)
from app.repositories.subject_repo import get_subject_by_slug
from app.schemas.files import (
    FileDeleteData,
    FileAssetItem,
    FileRecord,
    FilesData,
    FilesUploadData,
)
from app.services.presenters import require_id, require_uid
from app.services.upload_support import (
    build_asset_dir,
    build_raw_file_path,
    build_raw_markdown_path,
    build_temp_dir,
    resolve_storage_key_path,
    to_storage_key,
)
from app.utils.subject import validate_subject
from app.workflows.ingest import run_parse_file_workflow

logger = structlog.get_logger()


def _generate_file_uid() -> str:
    return f"file_{uuid.uuid4().hex}"


def _storage_key_to_runtime_url(storage_key: str | None) -> str | None:
    if not storage_key:
        return None
    encoded_parts = [quote(part) for part in storage_key.split("/") if part]
    if not encoded_parts:
        return None
    return f"/_assets/{'/'.join(encoded_parts)}"


def _asset_base_url(raw_file: RawFile) -> str | None:
    raw_file_id = raw_file.id
    if raw_file_id is None:
        return None
    asset_dir = build_asset_dir(_get_subject_slug_from_storage(raw_file.storage_key), raw_file_id)
    try:
        relative = asset_dir.relative_to(resolve_storage_key_path("."))
    except Exception:
        relative = Path(to_storage_key(asset_dir))
    return _storage_key_to_runtime_url(relative.as_posix())


def _read_assets(session: Session, raw_file: RawFile) -> list[FileAssetItem]:
    raw_file_id = require_id(raw_file.id, "RawFile.id")
    assets = list_assets_by_raw_file_id(session, raw_file_id)
    items: list[FileAssetItem] = []
    for asset in assets:
        asset_url = _storage_key_to_runtime_url(asset.storage_key)
        if not asset_url:
            continue
        items.append(
            FileAssetItem(
                name=asset.asset_name,
                url=asset_url,
                mime_type=asset.mime_type,
                asset_kind=asset.asset_kind,
                page_num=asset.page_num,
                width=asset.width,
                height=asset.height,
                ocr_text=asset.ocr_text,
            )
        )
    return items


def _get_subject_slug_from_storage(storage_key: str) -> str:
    parts = [part for part in storage_key.split("/") if part]
    return parts[0] if parts else ""


def _build_file_record(session: Session, raw_file: RawFile) -> FileRecord:
    assets = _read_assets(session, raw_file)
    asset_base_url = None
    if raw_file.id is not None:
        asset_base_url = _storage_key_to_runtime_url(
            to_storage_key(build_asset_dir(_get_subject_slug_from_storage(raw_file.storage_key), raw_file.id))
        )

    parse_metadata = {}
    if raw_file.parse_metadata_json:
        try:
            parse_metadata = json.loads(raw_file.parse_metadata_json)
        except json.JSONDecodeError:
            parse_metadata = {}

    return FileRecord(
        uid=require_uid(raw_file.uid, "RawFile.uid"),
        filename=raw_file.original_filename,
        filetype=raw_file.file_ext.lstrip("."),
        status=raw_file.status,
        ingest_status=raw_file.ingest_status,
        markdown_ready=bool(raw_file.parsed_markdown.strip()),
        asset_ready=bool(assets),
        error_message=raw_file.parse_error_message,
        file_size_bytes=raw_file.size_bytes,
        detected_language=raw_file.detected_language,
        estimated_pages=raw_file.estimated_pages,
        image_count=raw_file.image_count,
        parser_used=raw_file.parser_used or parse_metadata.get("parser_used"),
        markdown_content=raw_file.parsed_markdown,
        asset_base_url=asset_base_url,
        assets=assets,
        classification_json=raw_file.classification_json,
        quality_score=raw_file.quality_score,
        digest_current_step=raw_file.digest_current_step,
        parse_metadata_json=raw_file.parse_metadata_json,
        latest_updated_at=raw_file.updated_at,
        created_at=raw_file.created_at,
    )


def _build_upload_data(*, subject: str, raw_files: list[RawFile], started_parse_count: int, session: Session) -> FilesUploadData:
    return FilesUploadData(
        subject=subject,
        filenames=[item.original_filename for item in raw_files],
        uploaded_items=[_build_file_record(session, item) for item in raw_files],
        started_parse_count=started_parse_count,
    )


def _require_subject(session: Session, *, subject: str) -> Subject:
    record = get_subject_by_slug(session, subject)
    if record is None:
        raise SubjectRegistryNotFoundError(subject)
    return record


async def _save_uploaded_raw_files(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
) -> list[RawFile]:
    saved: list[RawFile] = []
    for file in files:
        saved.append(await save_uploaded_file(session, subject=subject, file=file))
    return saved


async def save_uploaded_file(
    session: Session,
    *,
    subject: str,
    file: UploadFile,
) -> RawFile:
    settings = get_settings()
    normalized_subject = validate_subject(subject)
    subject_record = _require_subject(session, subject=normalized_subject)
    subject_id = require_id(subject_record.id, "Subject.id")
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise FileTooLargeError(settings.max_upload_size_mb)

    filename = file.filename or "unknown"
    extension = Path(filename).suffix.lower() or ".bin"
    mime_type = file.content_type or mimetypes.guess_type(filename)[0]
    checksum_sha256 = hashlib.sha256(content).hexdigest()

    temp_dir = build_temp_dir(normalized_subject)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{extension}"
    temp_path.write_bytes(content)

    raw_file = create_raw_file(
        session,
        RawFile(
            user_id=subject_record.user_id,
            subject_id=subject_id,
            uid=_generate_file_uid(),
            original_filename=filename,
            file_ext=extension,
            mime_type=mime_type,
            storage_backend="local",
            storage_key=to_storage_key(temp_path),
            status=TaskStatus.PENDING.value,
            ingest_status=IngestStatus.PENDING.value,
            size_bytes=len(content),
            checksum_sha256=checksum_sha256,
        ),
    )
    raw_file_id = require_id(raw_file.id, "RawFile.id")
    final_path = build_raw_file_path(normalized_subject, raw_file_id, extension)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(temp_path), str(final_path))
    except Exception as exc:  # noqa: BLE001
        delete_raw_file(session, raw_file)
        temp_path.unlink(missing_ok=True)
        raise FileParseError(filename, reason=f"移动上传文件失败: {exc}") from exc

    return update_raw_file(
        session,
        raw_file,
        storage_key=to_storage_key(final_path),
        mime_type=mime_type,
        size_bytes=len(content),
        checksum_sha256=checksum_sha256,
    )


async def save_uploaded_files(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
) -> FilesUploadData:
    saved = await _save_uploaded_raw_files(session, subject=subject, files=files)
    return _build_upload_data(subject=subject, raw_files=saved, started_parse_count=0, session=session)


async def save_uploaded_files_and_request_parse(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
) -> tuple[FilesUploadData, list[int]]:
    saved = await _save_uploaded_raw_files(session, subject=subject, files=files)
    file_ids = [require_id(item.id, "RawFile.id") for item in saved]
    refreshed_items = _start_parse_for_files(session, subject=subject, file_ids=file_ids)
    return (
        _build_upload_data(
            subject=subject,
            raw_files=refreshed_items,
            started_parse_count=len(file_ids),
            session=session,
        ),
        file_ids,
    )


def get_subject_file_or_raise(session: Session, *, subject: str, file_id: int) -> RawFile:
    raw_file = get_raw_file_by_id(session, file_id)
    if raw_file is None:
        raise RawFileNotFoundError(file_id)
    subject_record = _require_subject(session, subject=subject)
    if raw_file.subject_id != require_id(subject_record.id, "Subject.id"):
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


def _start_parse_for_files(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
) -> list[RawFile]:
    raw_files = get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
    logger.info(
        "file_parse_state_transition_requested",
        subject=subject,
        requested_file_ids=file_ids,
        raw_file_states=[
            {
                "file_id": require_id(item.id, "RawFile.id"),
                "file_uid": require_uid(item.uid, "RawFile.uid"),
                "status": item.status,
                "filename": item.original_filename,
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
            parse_error_message=None,
            ingest_status=IngestStatus.CLASSIFYING.value,
            digest_current_step="ingest.parse.queued",
        )

    logger.info(
        "file_parse_state_transition_completed",
        subject=subject,
        accepted_file_ids=file_ids,
        accepted_file_uids=[require_uid(item.uid, "RawFile.uid") for item in raw_files],
        accepted_count=len(file_ids),
    )
    return get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)


async def run_parse_files_background(*, subject: str, file_ids: list[int]) -> None:
    settings = get_settings()
    concurrency = min(max(settings.ingest_parse_concurrency, len(file_ids), 5), 10)
    batch_logger = logger.bind(subject=subject, file_ids=file_ids)
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
                result = await run_parse_file_workflow(subject=subject, file_id=file_id)
            except Exception as exc:  # noqa: BLE001
                batch_logger.exception(
                    "file_parse_background_crashed",
                    file_id=file_id,
                    error=str(exc),
                )
                return

            if result.failed:
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
            else:
                batch_logger.info("file_parse_background_success", file_id=file_id)

    await asyncio.gather(*[asyncio.create_task(_run_one(file_id)) for file_id in file_ids])
    batch_logger.info("file_parse_background_completed")


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
    records = [_build_file_record(session, item) for item in raw_files]
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


def _delete_storage_path(storage_key: str | None) -> None:
    if not storage_key:
        return
    path = resolve_storage_key_path(storage_key)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    path.unlink(missing_ok=True)


def delete_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str],
) -> FileDeleteData:
    raw_files = get_subject_files_by_uid_or_raise(session, subject=subject, file_uids=file_uids)
    deleted_uids: list[str] = []

    for raw_file in raw_files:
        raw_file_id = require_id(raw_file.id, "RawFile.id")
        raw_file_uid = require_uid(raw_file.uid, "RawFile.uid")

        for asset in list_assets_by_raw_file_id(session, raw_file_id):
            _delete_storage_path(asset.storage_key)
        _delete_storage_path(raw_file.storage_key)
        _delete_storage_path(to_storage_key(build_raw_markdown_path(subject, raw_file_id)))
        _delete_storage_path(to_storage_key(build_asset_dir(subject, raw_file_id)))

        delete_raw_file(session, raw_file)
        deleted_uids.append(raw_file_uid)

    return FileDeleteData(deleted_file_uids=deleted_uids)


def sync_raw_file_assets(
    session: Session,
    *,
    raw_file: RawFile,
    assets: list[RawFileAsset],
) -> list[RawFileAsset]:
    raw_file_id = require_id(raw_file.id, "RawFile.id")
    return replace_raw_file_assets(session, raw_file_id=raw_file_id, assets=assets)
