"""File upload use cases."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.shared.infra.exceptions import FileCountLimitError, FileParseError, FileTooLargeError, UnsupportedFileTypeError
from app.shared.infra.settings import get_settings
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.storage import get_content_store
from app.models import IngestStatus, RawFile, TaskStatus
from app.repositories.files_repo import (
    create_raw_file,
    delete_raw_file,
    get_reusable_raw_file_by_content_hash,
    link_raw_files_to_subject,
    update_raw_file,
)
from app.schemas.files import FilesUploadData
from app.utils.path_helpers import build_temp_dir
from app.utils.presenters import require_id
from app.utils.subject import validate_subject_id
from app.workflows.ingest.intake.catalog import build_file_record
from app.workflows.ingest.intake.parse_dispatch import _start_parse_for_files


SUPPORTED_UPLOAD_EXTENSIONS = frozenset({".txt", ".doc", ".docx", ".pdf", ".ppt", ".pptx", ".md"})
DEFAULT_PARSE_REQUEST_SIGNATURE = "default"


def _generate_file_uid() -> str:
    return f"file_{uuid.uuid4().hex}"


def _validate_upload_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise UnsupportedFileTypeError(extension or filename or "unknown")
    return extension


def _build_upload_data(*, subject_id: str | None, raw_files: list[RawFile], started_parse_count: int) -> FilesUploadData:
    return FilesUploadData(
        subject_id=subject_id,
        filenames=[item.filename for item in raw_files],
        uploaded_items=[build_file_record(item) for item in raw_files],
        started_parse_count=started_parse_count,
    )


def _normalize_provider(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"", "auto", "default", "local"}:
        return None
    if normalized in {"paddleocr", "paddle-ocr"}:
        return "paddle_ocr"
    return normalized


def _is_secret_parse_key(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in {"api_token", "token", "access_token", "api_key"} or normalized.endswith("_api_token")


def _normalize_parse_request_value(key: str, value: object) -> object | None:
    if key == "requested_parser_provider":
        return _normalize_provider(value)
    if isinstance(value, dict):
        normalized_dict: dict[str, object] = {}
        secret_seen = False
        for child_key, child_value in sorted(value.items(), key=lambda item: str(item[0])):
            child_key_str = str(child_key)
            if _is_secret_parse_key(child_key_str):
                secret_seen = secret_seen or bool(child_value)
                continue
            normalized_child = _normalize_parse_request_value(child_key_str, child_value)
            if normalized_child is not None:
                normalized_dict[child_key_str] = normalized_child
        if secret_seen:
            normalized_dict["api_token_provided"] = True
        return normalized_dict or None
    if isinstance(value, list):
        normalized_list = [
            normalized_item
            for item in value
            if (normalized_item := _normalize_parse_request_value("", item)) is not None
        ]
        return normalized_list or None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if value is None:
        return None
    return value


def _normalize_parse_request_metadata(metadata: dict[str, object] | None) -> dict[str, object]:
    if not metadata:
        return {}
    normalized: dict[str, object] = {}
    for key, value in sorted(metadata.items(), key=lambda item: str(item[0])):
        key_str = str(key)
        if _is_secret_parse_key(key_str):
            if value:
                normalized["api_token_provided"] = True
            continue
        normalized_value = _normalize_parse_request_value(key_str, value)
        if normalized_value is not None:
            normalized[key_str] = normalized_value
    return normalized


def build_parse_request_signature(metadata: dict[str, object] | None) -> str:
    normalized = _normalize_parse_request_metadata(metadata)
    if not normalized:
        return DEFAULT_PARSE_REQUEST_SIGNATURE
    serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _unique_file_ids(raw_files: list[RawFile], *, status: str | None = None) -> list[int]:
    seen: set[int] = set()
    file_ids: list[int] = []
    for raw_file in raw_files:
        if status is not None and raw_file.status != status:
            continue
        raw_file_id = require_id(raw_file.id, "RawFile.id")
        if raw_file_id in seen:
            continue
        seen.add(raw_file_id)
        file_ids.append(raw_file_id)
    return file_ids


def _replace_refreshed_raw_files(raw_files: list[RawFile], refreshed: list[RawFile]) -> list[RawFile]:
    refreshed_by_id = {require_id(item.id, "RawFile.id"): item for item in refreshed}
    return [
        refreshed_by_id.get(require_id(item.id, "RawFile.id"), item)
        for item in raw_files
    ]


async def _save_uploaded_raw_files(
    session: Session,
    *,
    subject_id: str | None,
    owner_user_id: str,
    files: list[UploadFile],
    parse_request_metadata: dict[str, object] | None = None,
    origin_subject_name: str | None = None,
) -> list[RawFile]:
    max_files = get_settings().ingest.max_files_per_upload
    if len(files) > max_files:
        raise FileCountLimitError(max_files)

    saved: list[RawFile] = []
    for file in files:
        saved.append(
            await save_uploaded_file(
                session,
                subject_id=subject_id,
                owner_user_id=owner_user_id,
                file=file,
                parse_request_metadata=parse_request_metadata,
                origin_subject_name=origin_subject_name,
            )
        )
    return saved


async def save_uploaded_file(
    session: Session,
    *,
    subject_id: str | None = None,
    owner_user_id: str,
    file: UploadFile,
    parse_request_metadata: dict[str, object] | None = None,
    origin_subject_name: str | None = None,
) -> RawFile:
    settings = get_settings()
    cs = get_content_store()
    scope = cs.user_file_scope(user_id=owner_user_id)
    normalized_subject_id = validate_subject_id(subject_id) if subject_id else None
    content = await file.read()
    max_upload_size_mb = settings.ingest.max_upload_size_mb
    if len(content) > max_upload_size_mb * 1024 * 1024:
        raise FileTooLargeError(max_upload_size_mb)

    filename = file.filename or "unknown"
    extension = _validate_upload_extension(filename)
    content_hash = hashlib.sha256(content).hexdigest()
    parse_request_signature = build_parse_request_signature(parse_request_metadata)
    reusable_raw_file = get_reusable_raw_file_by_content_hash(
        session,
        user_id=owner_user_id,
        content_hash=content_hash,
        file_size_bytes=len(content),
        filetype=extension.lstrip("."),
        parse_request_signature=parse_request_signature,
        allow_completed_cross_signature=parse_request_signature == DEFAULT_PARSE_REQUEST_SIGNATURE,
    )
    if reusable_raw_file is not None:
        return reusable_raw_file

    file_uid = _generate_file_uid()
    temp_dir = build_temp_dir(normalized_subject_id or "library", user_id=owner_user_id)
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
    try:
        raw_file = create_raw_file(
            session,
            RawFile(
                uid=file_uid,
                origin_subject_id=normalized_subject_id,
                origin_subject_name=origin_subject_name,
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
                parse_request_signature=parse_request_signature,
            ),
        )
    except IntegrityError:
        session.rollback()
        temp_path.unlink(missing_ok=True)
        reusable_raw_file = get_reusable_raw_file_by_content_hash(
            session,
            user_id=owner_user_id,
            content_hash=content_hash,
            file_size_bytes=len(content),
            filetype=extension.lstrip("."),
            parse_request_signature=parse_request_signature,
            allow_completed_cross_signature=parse_request_signature == DEFAULT_PARSE_REQUEST_SIGNATURE,
        )
        if reusable_raw_file is not None:
            return reusable_raw_file
        raise
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
    subject_id: str | None = None,
    owner_user_id: str,
    files: list[UploadFile],
    origin_subject_name: str | None = None,
) -> FilesUploadData:
    saved = await _save_uploaded_raw_files(
        session,
        subject_id=subject_id,
        owner_user_id=owner_user_id,
        files=files,
        parse_request_metadata=None,
        origin_subject_name=origin_subject_name,
    )
    normalized_subject_id = validate_subject_id(subject_id) if subject_id else None
    if normalized_subject_id:
        saved = link_raw_files_to_subject(
            session,
            owner_user_id=owner_user_id,
            subject_id=normalized_subject_id,
            raw_files=saved,
        )
    return _build_upload_data(subject_id=normalized_subject_id, raw_files=saved, started_parse_count=0)


async def save_uploaded_files_and_request_parse(
    session: Session,
    *,
    subject_id: str | None = None,
    owner_user_id: str,
    files: list[UploadFile],
    parse_request_metadata: dict[str, object] | None = None,
    origin_subject_name: str | None = None,
) -> tuple[FilesUploadData, list[int]]:
    saved = await _save_uploaded_raw_files(
        session,
        subject_id=subject_id,
        owner_user_id=owner_user_id,
        files=files,
        parse_request_metadata=parse_request_metadata,
        origin_subject_name=origin_subject_name,
    )
    normalized_subject_id = validate_subject_id(subject_id) if subject_id else None
    if normalized_subject_id:
        saved = link_raw_files_to_subject(
            session,
            owner_user_id=owner_user_id,
            subject_id=normalized_subject_id,
            raw_files=saved,
        )
    file_ids = _unique_file_ids(saved, status=TaskStatus.PENDING.value)
    refreshed_items = []
    if file_ids:
        refreshed_items = _start_parse_for_files(
            session,
            owner_user_id=owner_user_id,
            subject_id=normalized_subject_id,
            file_ids=file_ids,
        )
    response_items = _replace_refreshed_raw_files(saved, refreshed_items)
    return _build_upload_data(
        subject_id=normalized_subject_id,
        raw_files=response_items,
        started_parse_count=len(file_ids),
    ), file_ids


__all__ = [
    "save_uploaded_file",
    "save_uploaded_files",
    "save_uploaded_files_and_request_parse",
]
