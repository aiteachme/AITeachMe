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
)
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import (
    create_raw_file,
    delete_raw_file,
    get_raw_file_by_id,
    list_raw_files_by_ids,
    list_raw_files_by_subject,
    list_raw_files_by_uids,
    update_raw_file,
)
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
    build_asset_name_prefix,
    build_raw_file_path,
    build_raw_markdown_path,
    build_temp_dir,
    delete_asset_files,
    get_data_dir,
    list_asset_files,
)
from app.utils.subject import validate_subject
from app.workflows.ingest import run_parse_file_workflow

logger = structlog.get_logger()


def _path_exists(path_value: str | None) -> bool:
    return bool(path_value and Path(path_value).exists())


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

    markdown_path = Path(markdown_path_value)
    if not markdown_path.exists():
        return ""

    return markdown_path.read_text(encoding="utf-8")


def _generate_file_uid() -> str:
    return f"file_{uuid.uuid4().hex}"


def _build_upload_data(*, subject: str, raw_files: list[RawFile], started_parse_count: int) -> FilesUploadData:
    return FilesUploadData(
        subject=subject,
        filenames=[item.filename for item in raw_files],
        uploaded_items=[build_file_record(item) for item in raw_files],
        started_parse_count=started_parse_count,
    )


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


def build_file_record(raw_file: RawFile) -> FileRecord:
    """Serialize a raw file into the unified file record."""

    file_uid = require_uid(raw_file.uid, "RawFile.uid")
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
        markdown_ready=_path_exists(raw_file.markdown_path),
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


async def save_uploaded_file(
    session: Session,
    *,
    subject: str,
    file: UploadFile,
) -> RawFile:
    """Save a single uploaded raw file."""

    settings = get_settings()
    normalized_subject = validate_subject(subject)
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise FileTooLargeError(settings.max_upload_size_mb)

    filename = file.filename or "unknown"
    extension = Path(filename).suffix.lower()
    content_hash = hashlib.sha256(content).hexdigest()
    temp_dir = build_temp_dir(normalized_subject)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{extension}"
    temp_path.write_bytes(content)

    raw_file = create_raw_file(
        session,
        RawFile(
            uid=_generate_file_uid(),
            subject=normalized_subject,
            filename=filename,
            filetype=extension.lstrip("."),
            file_path=str(temp_path),
            mime_type=file.content_type or mimetypes.guess_type(filename)[0],
            storage_backend="local",
            status=TaskStatus.PENDING.value,
            content_hash=content_hash,
            file_size_bytes=len(content),
            ingest_status=IngestStatus.PENDING.value,
        ),
    )
    raw_file_id = require_id(raw_file.id, "RawFile.id")
    final_path = build_raw_file_path(normalized_subject, raw_file_id, extension)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(temp_path), str(final_path))
    except Exception as exc:
        delete_raw_file(session, raw_file)
        temp_path.unlink(missing_ok=True)
        raise FileParseError(filename, reason=f"移动上传文件失败: {exc}") from exc

    return update_raw_file(
        session,
        raw_file,
        file_path=str(final_path),
        markdown_path=str(build_raw_markdown_path(normalized_subject, raw_file_id)),
        asset_dir=str(build_asset_dir(normalized_subject, raw_file_id)),
    )


async def save_uploaded_files(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
) -> FilesUploadData:
    """Save multiple uploaded raw files."""

    saved = await _save_uploaded_raw_files(session, subject=subject, files=files)
    return _build_upload_data(subject=subject, raw_files=saved, started_parse_count=0)


async def save_uploaded_files_and_request_parse(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
) -> tuple[FilesUploadData, list[int]]:
    """Save files and immediately enqueue ingest parsing in the same request."""

    saved = await _save_uploaded_raw_files(session, subject=subject, files=files)
    file_ids = [require_id(item.id, "RawFile.id") for item in saved]
    refreshed_items = _start_parse_for_files(session, subject=subject, file_ids=file_ids)
    return _build_upload_data(
        subject=subject,
        raw_files=refreshed_items,
        started_parse_count=len(file_ids),
    ), file_ids


def get_subject_file_or_raise(session: Session, *, subject: str, file_id: int) -> RawFile:
    """Load one file by subject or raise using internal ID."""

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
    """Load multiple files by subject or raise using internal IDs."""

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
    """Load multiple files by subject or raise using public UIDs."""

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
    """Move pending files into parsing state and return refreshed rows."""

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
        subject=subject,
        accepted_file_ids=file_ids,
        accepted_file_uids=[require_uid(item.uid, "RawFile.uid") for item in raw_files],
        accepted_count=len(file_ids),
    )
    return get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)


async def run_parse_files_background(*, subject: str, file_ids: list[int]) -> None:
    """Run the ingest workflow in background for a batch of files."""

    settings = get_settings()
    concurrency = max(settings.ingest_parse_concurrency, 1)
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
            except Exception as exc:
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

    await asyncio.gather(*[asyncio.create_task(_run_one(file_id)) for file_id in file_ids])
    batch_logger.info("file_parse_background_completed")


def list_subject_files(
    session: Session,
    *,
    subject: str,
) -> FilesData:
    """Return the full files dataset for one subject."""

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


def delete_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str],
) -> FileDeleteData:
    """Delete files and local artifacts."""

    raw_files = get_subject_files_by_uid_or_raise(session, subject=subject, file_uids=file_uids)
    deleted_uids: list[str] = []

    for raw_file in raw_files:
        raw_file_uid = require_uid(raw_file.uid, "RawFile.uid")

        for path_value in [raw_file.file_path, raw_file.markdown_path]:
            if path_value:
                Path(path_value).unlink(missing_ok=True)
        if raw_file.asset_dir:
            shutil.rmtree(raw_file.asset_dir, ignore_errors=True)
        else:
            delete_asset_files(
                str(build_asset_dir(raw_file.subject, require_id(raw_file.id, "RawFile.id"))),
                asset_name_prefix=_build_asset_name_prefix_for_raw_file(raw_file),
            )

        delete_raw_file(session, raw_file)
        deleted_uids.append(raw_file_uid)

    return FileDeleteData(deleted_file_uids=deleted_uids)
