"""Business logic for subject-scoped `files/*` endpoints."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import structlog
from fastapi import UploadFile
from sqlmodel import Session

from app.agents.ingest.orchestrator import parse_file
from app.core.config import get_settings
from app.core.exceptions import FileParseError, FileTooLargeError, RawFileNotFoundError
from app.repositories.ingest_repo import (
    create_raw_file,
    delete_raw_file,
    get_raw_file_by_id,
    list_raw_files_by_ids,
    update_raw_file,
)
from app.repositories.models import ParseStatus, RawFile
from app.services.presenters import require_id
from app.services.upload_support import (
    build_asset_dir,
    build_markdown_path,
    build_raw_file_path,
    build_temp_dir,
)
from app.utils.subject import validate_subject

logger = structlog.get_logger()


async def save_uploaded_file(
    session: Session,
    *,
    subject: str,
    file: UploadFile,
) -> RawFile:
    settings = get_settings()
    subject = validate_subject(subject)

    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise FileTooLargeError(settings.max_upload_size_mb)

    filename = file.filename or "unknown"
    extension = Path(filename).suffix.lower()

    temp_dir = build_temp_dir(subject)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{extension}"
    temp_path.write_bytes(content)

    raw_file = create_raw_file(
        session,
        RawFile(
            subject=subject,
            filename=filename,
            filetype=extension.lstrip("."),
            file_path=str(temp_path),
        ),
    )
    raw_file_id = require_id(raw_file.id, "RawFile.id")

    final_path = build_raw_file_path(subject, raw_file_id, extension)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.move(str(temp_path), str(final_path))
    except Exception as exc:
        delete_raw_file(session, raw_file_id)
        temp_path.unlink(missing_ok=True)
        raise FileParseError(filename, reason=f"Failed to move uploaded file. {exc}") from exc

    return update_raw_file(session, raw_file, file_path=str(final_path))


async def save_uploaded_files(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
) -> list[RawFile]:
    results: list[RawFile] = []
    for file in files:
        results.append(await save_uploaded_file(session, subject=subject, file=file))
    return results


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


async def parse_one_file(session: Session, raw_file: RawFile) -> RawFile:
    raw_file_id = require_id(raw_file.id, "RawFile.id")
    update_raw_file(
        session,
        raw_file,
        parse_status=ParseStatus.PARSING,
        parse_error=None,
    )

    markdown_path = build_markdown_path(raw_file.subject, raw_file_id)
    asset_dir = build_asset_dir(raw_file.subject, raw_file_id)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    try:
        markdown_text = await parse_file(raw_file.file_path)
        markdown_path.write_text(markdown_text, encoding="utf-8")
        return update_raw_file(
            session,
            raw_file,
            markdown_path=str(markdown_path),
            asset_dir=str(asset_dir),
            parse_status=ParseStatus.PARSED,
            parse_error=None,
        )
    except Exception as exc:
        logger.error("raw_file_parse_failed", file_id=raw_file_id, error=str(exc))
        return update_raw_file(
            session,
            raw_file,
            asset_dir=str(asset_dir),
            parse_status=ParseStatus.PARSE_FAILED,
            parse_error=str(exc),
        )


async def parse_files(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
) -> tuple[list[RawFile], list[dict[str, str | int]]]:
    raw_files = get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
    parsed: list[RawFile] = []
    failed: list[dict[str, str | int]] = []

    for raw_file in raw_files:
        updated = await parse_one_file(session, raw_file)
        if updated.parse_status == ParseStatus.PARSED:
            parsed.append(updated)
        else:
            failed.append(
                {
                    "file_id": require_id(updated.id, "RawFile.id"),
                    "error": updated.parse_error or "Parse failed.",
                }
            )

    return parsed, failed


def read_markdown_content(raw_file: RawFile) -> str:
    if not raw_file.markdown_path:
        return ""
    markdown_path = Path(raw_file.markdown_path)
    if not markdown_path.exists():
        return ""
    return markdown_path.read_text(encoding="utf-8")


def list_asset_payload(raw_file: RawFile) -> list[dict[str, str]]:
    if not raw_file.asset_dir:
        return []

    asset_dir = Path(raw_file.asset_dir)
    if not asset_dir.exists():
        return []

    assets: list[dict[str, str]] = []
    for child in sorted(asset_dir.iterdir()):
        if child.is_file():
            assets.append({"path": str(child)})
    return assets
