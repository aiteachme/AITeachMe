"""File upload use cases."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlmodel import Session

from app.shared.infra.settings import get_settings
from app.shared.infra.exceptions import FileCountLimitError, FileParseError, FileTooLargeError
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.storage import get_content_store
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import create_raw_file, delete_raw_file, link_raw_files_to_subject, update_raw_file
from app.schemas.files import FilesUploadData
from app.utils.path_helpers import (
    build_temp_dir,
)
from app.utils.presenters import require_id
from app.utils.subject import validate_subject
from app.workflows.support.files.catalog import build_file_record
from app.workflows.support.files.parsing import _start_parse_for_files


def _generate_file_uid() -> str:
    return f"file_{uuid.uuid4().hex}"


def _build_upload_data(*, subject: str | None, raw_files: list[RawFile], started_parse_count: int) -> FilesUploadData:
    return FilesUploadData(
        subject=subject or "library",
        filenames=[item.filename for item in raw_files],
        uploaded_items=[build_file_record(item) for item in raw_files],
        started_parse_count=started_parse_count,
    )


async def _save_uploaded_raw_files(
    session: Session,
    *,
    subject: str | None,
    owner_user_id: str,
    files: list[UploadFile],
    parse_request_metadata: dict[str, object] | None = None,
) -> list[RawFile]:
    max_files = get_settings().ingest.max_files_per_upload
    if len(files) > max_files:
        raise FileCountLimitError(max_files)

    saved: list[RawFile] = []
    for file in files:
        saved.append(
            await save_uploaded_file(
                session,
                subject=subject,
                owner_user_id=owner_user_id,
                file=file,
                parse_request_metadata=parse_request_metadata,
            )
        )
    return saved


async def save_uploaded_file(
    session: Session,
    *,
    subject: str | None = None,
    owner_user_id: str,
    file: UploadFile,
    parse_request_metadata: dict[str, object] | None = None,
) -> RawFile:
    settings = get_settings()
    cs = get_content_store()
    scope = cs.user_file_scope(user_id=owner_user_id)
    normalized_subject = validate_subject(subject) if subject else None
    content = await file.read()
    max_upload_size_mb = settings.ingest.max_upload_size_mb
    if len(content) > max_upload_size_mb * 1024 * 1024:
        raise FileTooLargeError(max_upload_size_mb)

    filename = file.filename or "unknown"
    extension = Path(filename).suffix.lower()
    file_uid = _generate_file_uid()
    content_hash = hashlib.sha256(content).hexdigest()
    temp_dir = build_temp_dir(normalized_subject or "library", user_id=owner_user_id)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{extension}"
    temp_path.write_bytes(content)

    storage_backend = "s3" if is_cloud_mode() else "local"
    parse_request_json = None
    if parse_request_metadata:
        try:
            parse_request_json = json.dumps(parse_request_metadata, ensure_ascii=False)
        except Exception:
            parse_request_json = None
    raw_file = create_raw_file(
        session,
        RawFile(
            uid=file_uid,
            subject=normalized_subject,
            user_id=owner_user_id,
            filename=filename,
            filetype=extension.lstrip("."),
            file_path=str(temp_path),
            mime_type=file.content_type or mimetypes.guess_type(filename)[0],
            storage_backend=storage_backend,
            status=TaskStatus.PENDING.value,
            content_hash=content_hash,
            file_size_bytes=len(content),
            ingest_status=IngestStatus.PENDING.value,
            parse_metadata_json=parse_request_json or "{}",
        ),
    )
    raw_file_key = scope.raw_file_key(file_uid=file_uid, filename=filename, extension=extension)
    raw_markdown_key = scope.raw_markdown_key(file_uid=file_uid, filename=filename)
    asset_prefix = scope.asset_prefix(file_uid=file_uid, filename=filename)

    try:
        await cs.write_file(raw_file_key, temp_path)
    except Exception as exc:
        delete_raw_file(session, raw_file)
        temp_path.unlink(missing_ok=True)
        reason = "上传文件到 OSS 失败" if is_cloud_mode() else "保存上传文件失败"
        raise FileParseError(filename, reason=f"{reason}: {exc}") from exc
    temp_path.unlink(missing_ok=True)

    return update_raw_file(
        session,
        raw_file,
        file_path=raw_file_key,
        markdown_path=raw_markdown_key,
        asset_dir=asset_prefix.rstrip("/"),
    )


async def save_uploaded_files(
    session: Session,
    *,
    subject: str | None = None,
    owner_user_id: str,
    files: list[UploadFile],
) -> FilesUploadData:
    saved = await _save_uploaded_raw_files(
        session,
        subject=subject,
        owner_user_id=owner_user_id,
        files=files,
        parse_request_metadata=None,
    )
    if subject:
        saved = link_raw_files_to_subject(
            session,
            owner_user_id=owner_user_id,
            subject=validate_subject(subject),
            raw_files=saved,
        )
    return _build_upload_data(subject=subject, raw_files=saved, started_parse_count=0)


async def save_uploaded_files_and_request_parse(
    session: Session,
    *,
    subject: str | None = None,
    owner_user_id: str,
    files: list[UploadFile],
    parse_request_metadata: dict[str, object] | None = None,
) -> tuple[FilesUploadData, list[int]]:
    saved = await _save_uploaded_raw_files(
        session,
        subject=subject,
        owner_user_id=owner_user_id,
        files=files,
        parse_request_metadata=parse_request_metadata,
    )
    normalized_subject = validate_subject(subject) if subject else None
    if normalized_subject:
        saved = link_raw_files_to_subject(
            session,
            owner_user_id=owner_user_id,
            subject=normalized_subject,
            raw_files=saved,
        )
    file_ids = [require_id(item.id, "RawFile.id") for item in saved]
    refreshed_items = _start_parse_for_files(
        session,
        owner_user_id=owner_user_id,
        subject=normalized_subject,
        file_ids=file_ids,
    )
    return _build_upload_data(
        subject=normalized_subject,
        raw_files=refreshed_items,
        started_parse_count=len(file_ids),
    ), file_ids


__all__ = [
    "save_uploaded_file",
    "save_uploaded_files",
    "save_uploaded_files_and_request_parse",
]
