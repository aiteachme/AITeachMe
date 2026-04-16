"""File upload use cases."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlmodel import Session

from app.shared.infra.settings import get_settings
from app.shared.infra.exceptions import FileCountLimitError, FileParseError, FileTooLargeError
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.storage import get_artifact_store, get_content_store
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import create_raw_file, delete_raw_file, update_raw_file
from app.schemas.files import FilesUploadData
from app.utils.path_helpers import (
    build_asset_dir,
    build_raw_file_path,
    build_raw_markdown_path,
    build_temp_dir,
)
from app.utils.presenters import require_id
from app.utils.subject import validate_subject
from app.workflows.support.files.catalog import build_file_record
from app.workflows.support.files.parsing import _start_parse_for_files


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
    parse_request_metadata: dict[str, object] | None = None,
) -> list[RawFile]:
    max_files = get_settings().files.max_files_per_upload
    if len(files) > max_files:
        raise FileCountLimitError(max_files)

    saved: list[RawFile] = []
    for file in files:
        saved.append(
            await save_uploaded_file(
                session,
                subject=subject,
                file=file,
                parse_request_metadata=parse_request_metadata,
            )
        )
    return saved


async def save_uploaded_file(
    session: Session,
    *,
    subject: str,
    file: UploadFile,
    parse_request_metadata: dict[str, object] | None = None,
) -> RawFile:
    settings = get_settings()
    store = get_artifact_store()
    normalized_subject = validate_subject(subject)
    content = await file.read()
    max_upload_size_mb = settings.files.max_upload_size_mb
    if len(content) > max_upload_size_mb * 1024 * 1024:
        raise FileTooLargeError(max_upload_size_mb)

    filename = file.filename or "unknown"
    extension = Path(filename).suffix.lower()
    content_hash = hashlib.sha256(content).hexdigest()
    temp_dir = build_temp_dir(normalized_subject)
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
            uid=_generate_file_uid(),
            subject=normalized_subject,
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
    raw_file_id = require_id(raw_file.id, "RawFile.id")

    cs = get_content_store()
    if is_cloud_mode():
        storage_key = f"{normalized_subject}/raw_files/{raw_file_id}{extension}"
        try:
            await store.write_file(storage_key, temp_path)
        except Exception as exc:
            delete_raw_file(session, raw_file)
            temp_path.unlink(missing_ok=True)
            raise FileParseError(filename, reason=f"上传文件到 OSS 失败: {exc}") from exc
        temp_path.unlink(missing_ok=True)
        return update_raw_file(
            session,
            raw_file,
            file_path=storage_key,
            markdown_path=cs.raw_markdown_key(normalized_subject, raw_file_id),
            asset_dir=cs.asset_prefix(normalized_subject, raw_file_id).rstrip("/"),
        )

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
    saved = await _save_uploaded_raw_files(
        session,
        subject=subject,
        files=files,
        parse_request_metadata=None,
    )
    return _build_upload_data(subject=subject, raw_files=saved, started_parse_count=0)


async def save_uploaded_files_and_request_parse(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
    parse_request_metadata: dict[str, object] | None = None,
) -> tuple[FilesUploadData, list[int]]:
    saved = await _save_uploaded_raw_files(
        session,
        subject=subject,
        files=files,
        parse_request_metadata=parse_request_metadata,
    )
    file_ids = [require_id(item.id, "RawFile.id") for item in saved]
    refreshed_items = _start_parse_for_files(session, subject=subject, file_ids=file_ids)
    return _build_upload_data(
        subject=subject,
        raw_files=refreshed_items,
        started_parse_count=len(file_ids),
    ), file_ids


__all__ = [
    "save_uploaded_file",
    "save_uploaded_files",
    "save_uploaded_files_and_request_parse",
]
