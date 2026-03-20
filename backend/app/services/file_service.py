"""文件服务层。"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

import structlog
from fastapi import UploadFile
from sqlmodel import Session

from app.agents.ingest.classifier import classify_file
from app.agents.ingest.orchestrator import parse_file
from app.core.config import get_settings
from app.core.database import managed_session
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
    update_raw_file,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.files import (
    FileDeleteData,
    FileGetData,
    FileItem,
    FileStatusData,
    FilesParseData,
    FilesUploadData,
)
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
    """保存单个上传文件。"""

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
            subject=normalized_subject,
            filename=filename,
            filetype=extension.lstrip("."),
            file_path=str(temp_path),
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
        raise FileParseError(filename, reason=f"移动上传文件失败：{exc}") from exc

    return update_raw_file(session, raw_file, file_path=str(final_path))


async def save_uploaded_files(
    session: Session,
    *,
    subject: str,
    files: list[UploadFile],
) -> FilesUploadData:
    """批量保存上传文件。"""

    saved: list[RawFile] = []
    for file in files:
        saved.append(await save_uploaded_file(session, subject=subject, file=file))
    return FilesUploadData(
        subject=subject,
        file_ids=[require_id(item.id, "RawFile.id") for item in saved],
        filenames=[item.filename for item in saved],
    )


def get_subject_file_or_raise(session: Session, *, subject: str, file_id: int) -> RawFile:
    """按学科读取文件，找不到则抛错。"""

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
    """按学科批量读取文件。"""

    items = list_raw_files_by_ids(session, subject, file_ids)
    found_ids = {require_id(item.id, "RawFile.id") for item in items}
    missing = [file_id for file_id in file_ids if file_id not in found_ids]
    if missing:
        raise RawFileNotFoundError(missing[0])
    order = {file_id: index for index, file_id in enumerate(file_ids)}
    return sorted(items, key=lambda item: order[require_id(item.id, "RawFile.id")])


def request_files_parse(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
) -> FilesParseData:
    """受理批量解析请求。"""

    raw_files = get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
    logger.info(
        "file_parse_requested",
        subject=subject,
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
    accepted_ids: list[int] = []
    for raw_file in raw_files:
        raw_file_id = require_id(raw_file.id, "RawFile.id")
        if raw_file.status != TaskStatus.PENDING.value:
            raise InvalidRawFileStateError(raw_file_id, raw_file.status, TaskStatus.PENDING.value)
        update_raw_file(
            session,
            raw_file,
            status=TaskStatus.PROCESSING.value,
            error_message=None,
            ingest_status=IngestStatus.CLASSIFYING.value,
        )
        accepted_ids.append(raw_file_id)
    logger.info(
        "file_parse_accepted",
        subject=subject,
        accepted_file_ids=accepted_ids,
        accepted_count=len(accepted_ids),
    )
    return FilesParseData(accepted_file_ids=accepted_ids)


def retry_file_parse(
    session: Session,
    *,
    subject: str,
    file_id: int,
) -> FilesParseData:
    """重试失败文件。"""

    raw_file = get_subject_file_or_raise(session, subject=subject, file_id=file_id)
    if raw_file.status != TaskStatus.FAILED.value:
        raise InvalidRawFileStateError(file_id, raw_file.status, TaskStatus.FAILED.value)
    update_raw_file(
        session,
        raw_file,
        status=TaskStatus.PROCESSING.value,
        error_message=None,
        ingest_status=IngestStatus.CLASSIFYING.value,
    )
    return FilesParseData(accepted_file_ids=[file_id])


async def run_parse_files_background(*, subject: str, file_ids: list[int]) -> None:
    """后台执行批量解析。"""

    batch_logger = logger.bind(subject=subject, file_ids=file_ids)
    batch_logger.info("file_parse_background_started", file_count=len(file_ids))
    with managed_session() as session:
        for file_id in file_ids:
            raw_file = get_raw_file_by_id(session, file_id)
            if raw_file is None or raw_file.subject != subject:
                batch_logger.warning(
                    "file_parse_background_skipped",
                    file_id=file_id,
                    reason="raw_file_missing_or_subject_mismatch",
                )
                continue
            batch_logger.info(
                "file_parse_background_dispatch",
                file_id=file_id,
                status=raw_file.status,
                markdown_ready=bool(raw_file.markdown_path),
            )
            await _parse_one_file(session, raw_file)
    batch_logger.info("file_parse_background_completed")


async def _parse_one_file(session: Session, raw_file: RawFile) -> RawFile:
    """执行单文件解析任务（含分类 → 解析 → 统计）。"""

    raw_file_id = require_id(raw_file.id, "RawFile.id")
    file_logger = logger.bind(
        subject=raw_file.subject,
        file_id=raw_file_id,
        filename=raw_file.filename,
        file_path=raw_file.file_path,
    )
    started_at = time.monotonic()
    markdown_path = build_markdown_path(raw_file.subject, raw_file_id)
    asset_dir = build_asset_dir(raw_file.subject, raw_file_id)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ── 1. 文件指纹 ──
        file_bytes = Path(raw_file.file_path).read_bytes()
        content_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size_bytes = len(file_bytes)

        # ── 2. 轻量分类 ──
        classification = classify_file(raw_file.file_path, raw_file.filetype)
        classification_payload = json.dumps(classification.to_dict(), ensure_ascii=False)
        file_logger.info(
            "file_classify_done",
            category=classification.file_category,
            estimated_pages=classification.estimated_pages,
            language=classification.detected_language,
        )
        update_raw_file(
            session,
            raw_file,
            estimated_pages=classification.estimated_pages,
            detected_language=classification.detected_language,
            classification_result=classification_payload,
            ingest_status=IngestStatus.PARSING.value,
        )

        # ── 3. 解析 ──
        file_logger.info(
            "file_parse_started",
            markdown_path=str(markdown_path),
            asset_dir=str(asset_dir),
        )
        markdown_text = await parse_file(raw_file.file_path, asset_dir)
        markdown_path.write_text(markdown_text, encoding="utf-8")

        # ── 4. 统计提取的图片数 ──
        image_count = len(list(asset_dir.glob("*"))) if asset_dir.exists() else 0
        elapsed = round(time.monotonic() - started_at, 2)

        # ── 5. 构建解析元数据 ──
        parse_meta = json.dumps({
            "parser_chain": classification.recommended_parser,
            "fallbacks": classification.fallback_parsers,
            "elapsed_s": elapsed,
            "markdown_chars": len(markdown_text),
            "image_count": image_count,
        }, ensure_ascii=False)

        # ── 6. 更新记录 ──
        updated = update_raw_file(
            session,
            raw_file,
            markdown_path=str(markdown_path),
            asset_dir=str(asset_dir),
            status=TaskStatus.COMPLETED.value,
            error_message=None,
            content_hash=content_hash,
            file_size_bytes=file_size_bytes,
            estimated_pages=classification.estimated_pages,
            detected_language=classification.detected_language,
            classification_result=classification_payload,
            parse_metadata=parse_meta,
            image_count=image_count,
            ingest_status=IngestStatus.READY_FOR_DIGEST.value,
        )
        file_logger.info(
            "file_parse_completed",
            status=updated.status,
            images=image_count,
            elapsed_s=elapsed,
        )
        return updated
    except Exception as exc:
        file_logger.error(
            "parse_file_failed",
            error=str(exc),
            elapsed_s=round(time.monotonic() - started_at, 2),
            exc_info=True,
        )
        updated = update_raw_file(
            session,
            raw_file,
            asset_dir=str(asset_dir),
            status=TaskStatus.FAILED.value,
            error_message=str(exc),
            ingest_status=IngestStatus.FAILED.value,
        )
        file_logger.info(
            "file_parse_marked_failed",
            status=updated.status,
            error_message=updated.error_message,
        )
        return updated


def list_files(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
    status: str | None = None,
) -> PaginatedData[FileItem]:
    """分页读取文件列表。"""

    items, total = list_raw_files_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
        status=status,
    )
    return build_paginated_data(
        items=[
            FileItem(
                id=require_id(item.id, "RawFile.id"),
                filename=item.filename,
                filetype=item.filetype,
                status=item.status,
                markdown_ready=bool(item.markdown_path),
                latest_updated_at=item.updated_at,
                created_at=item.created_at,
            )
            for item in items
        ],
        page=page,
        size=size,
        total=total,
    )


def get_file_status(
    session: Session,
    *,
    subject: str,
    file_id: int,
) -> FileStatusData:
    """读取单文件状态。"""

    raw_file = get_subject_file_or_raise(session, subject=subject, file_id=file_id)
    return FileStatusData(
        file_id=file_id,
        upload_status=TaskStatus.COMPLETED.value,
        status=raw_file.status,
        markdown_ready=bool(raw_file.markdown_path),
        asset_ready=bool(raw_file.asset_dir),
        error_message=raw_file.error_message,
        latest_updated_at=raw_file.updated_at,
    )


def get_file_result(
    session: Session,
    *,
    subject: str,
    file_id: int,
) -> FileGetData:
    """读取单文件解析结果。"""

    raw_file = get_subject_file_or_raise(session, subject=subject, file_id=file_id)
    markdown_content = ""
    if raw_file.markdown_path:
        markdown_path = Path(raw_file.markdown_path)
        if markdown_path.exists():
            markdown_content = markdown_path.read_text(encoding="utf-8")

    assets: list[dict[str, str]] = []
    if raw_file.asset_dir:
        asset_dir = Path(raw_file.asset_dir)
        if asset_dir.exists():
            assets = [{"path": str(path)} for path in sorted(asset_dir.iterdir()) if path.is_file()]

    return FileGetData(
        file_id=file_id,
        filename=raw_file.filename,
        status=raw_file.status,
        markdown_content=markdown_content,
        assets=assets,
    )


def delete_files(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
) -> FileDeleteData:
    """删除文件及其本地产物。"""

    raw_files = get_subject_files_or_raise(session, subject=subject, file_ids=file_ids)
    deleted_ids: list[int] = []
    for raw_file in raw_files:
        raw_file_id = require_id(raw_file.id, "RawFile.id")

        for path_value in [raw_file.file_path, raw_file.markdown_path]:
            if path_value:
                Path(path_value).unlink(missing_ok=True)
        if raw_file.asset_dir:
            shutil.rmtree(raw_file.asset_dir, ignore_errors=True)

        delete_raw_file(session, raw_file)
        deleted_ids.append(raw_file_id)

    return FileDeleteData(deleted_file_ids=deleted_ids)
