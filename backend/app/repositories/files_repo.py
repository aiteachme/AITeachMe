"""Raw file data-access helpers."""

from __future__ import annotations

import mimetypes
from datetime import datetime
from typing import Iterable

from sqlalchemy import delete as sa_delete, or_
from sqlalchemy.orm import defer
from sqlmodel import Session, func, select

from app.models import RawFile, RawFileAsset, Course, CourseFileLink, TaskStatus
from app.shared.infra.storage import get_content_store, run_store_sync
from app.utils.time import utcnow

_UNSET = object()


def create_raw_file(session: Session, raw_file: RawFile) -> RawFile:
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def get_raw_file_by_id(session: Session, file_id: str) -> RawFile | None:
    return session.get(RawFile, file_id)


def get_raw_file_by_id_for_user(
    session: Session,
    *,
    user_id: str,
    file_id: str,
    include_markdown_content: bool = True,
) -> RawFile | None:
    stmt = select(RawFile).where(RawFile.user_id == user_id, RawFile.id == file_id)
    if not include_markdown_content:
        stmt = stmt.options(defer(RawFile.markdown_content))
    return session.exec(stmt).first()


def get_raw_file_markdown_chunk_for_user(
    session: Session,
    *,
    user_id: str,
    file_id: str,
    offset: int,
    limit: int,
) -> tuple[str, int] | None:
    """Read a character slice without transferring the full Markdown column."""

    markdown = func.coalesce(RawFile.markdown_content, "")
    stmt = select(
        func.substr(markdown, offset + 1, limit),
        func.length(markdown),
    ).where(RawFile.user_id == user_id, RawFile.id == file_id)
    row = session.exec(stmt).first()
    if row is None:
        return None
    chunk, total_chars = row
    return str(chunk or ""), int(total_chars or 0)


def get_reusable_raw_file_by_content_hash(
    session: Session,
    *,
    user_id: str,
    content_hash: str,
    file_size_bytes: int,
    filetype: str,
    parse_request_signature: str,
    allow_completed_cross_signature: bool = False,
) -> RawFile | None:
    """Return an existing user-owned file that can satisfy the same upload."""

    if not content_hash or file_size_bytes is None or not filetype or not parse_request_signature:
        return None

    filters = [
        RawFile.user_id == user_id,
        RawFile.content_hash == content_hash,
        RawFile.file_size_bytes == file_size_bytes,
        RawFile.filetype == filetype.lstrip("."),
        RawFile.status != TaskStatus.FAILED.value,
    ]
    if allow_completed_cross_signature:
        filters.append(
            or_(
                RawFile.parse_request_signature == parse_request_signature,
                RawFile.status == TaskStatus.COMPLETED.value,
            )
        )
    else:
        filters.append(RawFile.parse_request_signature == parse_request_signature)

    stmt = (
        select(RawFile)
        .options(defer(RawFile.markdown_content))
        .where(*filters)
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    candidates = list(session.exec(stmt).all())
    if not candidates:
        return None
    return sorted(candidates, key=_reusable_raw_file_sort_key)[0]


def _datetime_ts(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0


def _parser_rank(raw_file: RawFile) -> int:
    parser = (raw_file.parser_used or "").strip().lower()
    if parser == "paddle_ocr":
        return 0
    if parser == "mineru":
        return 1
    return 2


def _reusable_raw_file_sort_key(raw_file: RawFile) -> tuple[int, int, float, str]:
    status_rank = {
        TaskStatus.COMPLETED.value: 0,
        TaskStatus.PROCESSING.value: 1,
        TaskStatus.PENDING.value: 2,
    }.get(raw_file.status, 3)
    parser_rank = _parser_rank(raw_file) if raw_file.status == TaskStatus.COMPLETED.value else 99
    time_rank = (
        -_datetime_ts(raw_file.updated_at)
        if raw_file.status == TaskStatus.COMPLETED.value
        else _datetime_ts(raw_file.created_at)
    )
    return (status_rank, parser_rank, time_rank, raw_file.id or "")


def _linked_raw_file_ids_for_course(course_id: str):
    return select(CourseFileLink.file_id).where(CourseFileLink.course_id == course_id)


def _course_membership_condition(course_id: str):
    return RawFile.id.in_(_linked_raw_file_ids_for_course(course_id))  # type: ignore[union-attr]


def list_raw_files_by_ids(
    session: Session,
    course_id: str,
    file_ids: list[str],
) -> list[RawFile]:
    if not file_ids:
        return []

    stmt = (
        select(RawFile)
        .where(_course_membership_condition(course_id), RawFile.id.in_(file_ids))  # type: ignore[union-attr]
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_raw_files_by_ids_for_user(
    session: Session,
    *,
    user_id: str,
    file_ids: list[str],
) -> list[RawFile]:
    if not file_ids:
        return []

    stmt = (
        select(RawFile)
        .where(RawFile.user_id == user_id, RawFile.id.in_(file_ids))  # type: ignore[union-attr]
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_raw_files_by_course(
    session: Session,
    course_id: str,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[RawFile], int]:
    filters = [_course_membership_condition(course_id)]
    if status:
        filters.append(RawFile.status == status)

    total = int(session.exec(select(func.count()).select_from(RawFile).where(*filters)).one())
    stmt = (
        select(RawFile)
        .options(defer(RawFile.markdown_content))
        .where(*filters)
        .order_by(RawFile.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def list_all_raw_files_by_course(session: Session, course_id: str) -> list[RawFile]:
    stmt = (
        select(RawFile)
        .where(_course_membership_condition(course_id))
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_raw_files_by_user(
    session: Session,
    *,
    user_id: str,
    file_ids: list[str] | None = None,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[RawFile], int]:
    filters = [RawFile.user_id == user_id]
    if file_ids:
        filters.append(RawFile.id.in_(file_ids))  # type: ignore[union-attr]
    if status:
        filters.append(RawFile.status == status)

    total = int(session.exec(select(func.count()).select_from(RawFile).where(*filters)).one())
    stmt = (
        select(RawFile)
        .options(defer(RawFile.markdown_content))
        .where(*filters)
        .order_by(RawFile.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def raw_file_belongs_to_course(session: Session, *, raw_file: RawFile, course_id: str) -> bool:
    if raw_file.id is None:
        return False
    stmt = select(CourseFileLink.id).where(
        CourseFileLink.course_id == course_id,
        CourseFileLink.file_id == raw_file.id,
    )
    return session.exec(stmt).first() is not None


def link_raw_files_to_course(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str,
    raw_files: list[RawFile],
) -> list[RawFile]:
    raw_file_ids = list(dict.fromkeys(item.id for item in raw_files if item.id))
    if not raw_file_ids:
        return []

    existing_link_ids = set(
        session.exec(
            select(CourseFileLink.file_id).where(
                CourseFileLink.user_id == owner_user_id,
                CourseFileLink.course_id == course_id,
                CourseFileLink.file_id.in_(raw_file_ids),  # type: ignore[union-attr]
            )
        ).all()
    )

    now = utcnow()
    for raw_file in raw_files:
        if not raw_file.id or raw_file.user_id != owner_user_id:
            continue
        if raw_file.id not in existing_link_ids:
            session.add(
                CourseFileLink(
                    user_id=owner_user_id,
                    course_id=course_id,
                    file_id=raw_file.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing_link_ids.add(raw_file.id)

    session.commit()
    for raw_file in raw_files:
        session.refresh(raw_file)
    return raw_files


def unlink_raw_files_from_course(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str,
    raw_files: list[RawFile],
    commit: bool = True,
) -> list[RawFile]:
    raw_file_ids = [item.id for item in raw_files if item.id]
    if not raw_file_ids:
        return []

    session.exec(
        sa_delete(CourseFileLink).where(
            CourseFileLink.user_id == owner_user_id,
            CourseFileLink.course_id == course_id,
            CourseFileLink.file_id.in_(raw_file_ids),  # type: ignore[union-attr]
        )
    )
    session.flush()

    if commit:
        session.commit()
        for raw_file in raw_files:
            session.refresh(raw_file)
    return raw_files


def unlink_all_courses_for_raw_file(session: Session, *, file_id: str) -> None:
    session.exec(sa_delete(CourseFileLink).where(CourseFileLink.file_id == file_id))


def count_course_links_for_raw_file(session: Session, *, file_id: str) -> int:
    return int(
        session.exec(
            select(func.count()).select_from(CourseFileLink).where(CourseFileLink.file_id == file_id)
        ).one()
    )


def list_linked_courses_for_raw_file(session: Session, *, file_id: str) -> list[Course]:
    stmt = (
        select(Course)
        .join(CourseFileLink, CourseFileLink.course_id == Course.id)
        .where(CourseFileLink.file_id == file_id)
        .order_by(Course.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def update_raw_file(
    session: Session,
    raw_file: RawFile,
    *,
    file_path: str | None | object = _UNSET,
    markdown_path: str | None | object = _UNSET,
    asset_dir: str | None | object = _UNSET,
    parsed_markdown: str | object = _UNSET,
    parser_used: str | None | object = _UNSET,
    parse_metadata_json: str | object = _UNSET,
    parse_progress_json: str | object = _UNSET,
    parse_request_signature: str | object = _UNSET,
    parse_metadata: str | None | object = _UNSET,
    parse_error_message: str | None | object = _UNSET,
    error_message: str | None | object = _UNSET,
    classification_json: str | object = _UNSET,
    classification_result: str | None | object = _UNSET,
    quality_score: float | None | object = _UNSET,
    image_count: int | None | object = _UNSET,
    status: str | None = None,
    ingest_status: str | object = _UNSET,
    digest_current_step: str | None | object = _UNSET,
    current_step: str | None | object = _UNSET,
    mime_type: str | None | object = _UNSET,
    storage_key: str | object = _UNSET,
    size_bytes: int | None | object = _UNSET,
    file_size_bytes: int | None | object = _UNSET,
    checksum_sha256: str | None | object = _UNSET,
    content_hash: str | None | object = _UNSET,
    estimated_pages: int | None | object = _UNSET,
    detected_language: str | None | object = _UNSET,
) -> RawFile:
    if file_path is not _UNSET:
        raw_file.file_path = file_path
    if markdown_path is not _UNSET:
        raw_file.markdown_path = markdown_path
    if asset_dir is not _UNSET:
        raw_file.asset_dir = asset_dir
    if parsed_markdown is not _UNSET:
        raw_file.parsed_markdown = str(parsed_markdown)
    if parser_used is not _UNSET:
        raw_file.parser_used = None if parser_used is None else str(parser_used)
    if parse_metadata_json is not _UNSET:
        raw_file.parse_metadata_json = str(parse_metadata_json)
    if parse_progress_json is not _UNSET:
        raw_file.parse_progress_json = str(parse_progress_json)
    if parse_request_signature is not _UNSET:
        raw_file.parse_request_signature = str(parse_request_signature)
    if parse_metadata is not _UNSET:
        raw_file.parse_metadata = parse_metadata
    if parse_error_message is not _UNSET:
        raw_file.parse_error_message = parse_error_message
    if error_message is not _UNSET:
        raw_file.error_message = error_message
    if classification_json is not _UNSET:
        raw_file.classification_json = str(classification_json)
    if classification_result is not _UNSET:
        raw_file.classification_result = classification_result
    if quality_score is not _UNSET:
        raw_file.quality_score = quality_score
    if image_count is not _UNSET:
        raw_file.image_count = image_count
    if status is not None:
        raw_file.status = status
    if ingest_status is not _UNSET:
        raw_file.ingest_status = str(ingest_status)
    if digest_current_step is not _UNSET:
        raw_file.digest_current_step = digest_current_step
    if current_step is not _UNSET:
        raw_file.current_step = current_step
    if mime_type is not _UNSET:
        raw_file.mime_type = mime_type
    if storage_key is not _UNSET:
        raw_file.storage_key = str(storage_key)
    if size_bytes is not _UNSET:
        raw_file.size_bytes = size_bytes
    if file_size_bytes is not _UNSET:
        raw_file.file_size_bytes = file_size_bytes
    if checksum_sha256 is not _UNSET:
        raw_file.checksum_sha256 = checksum_sha256
    if content_hash is not _UNSET:
        raw_file.content_hash = content_hash
    if estimated_pages is not _UNSET:
        raw_file.estimated_pages = estimated_pages
    if detected_language is not _UNSET:
        raw_file.detected_language = detected_language
    raw_file.updated_at = utcnow()
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def replace_raw_file_assets(
    session: Session,
    *,
    file_id: str,
    assets: Iterable[RawFileAsset],
) -> list[RawFileAsset]:
    del session, file_id
    return list(assets)


def list_assets_by_raw_file_id(session: Session, file_id: str) -> list[RawFileAsset]:
    raw_file = get_raw_file_by_id(session, file_id)
    if raw_file is None:
        return []

    asset_dir = raw_file.asset_dir
    if not asset_dir:
        if raw_file.user_id:
            scope = get_content_store().user_file_scope(user_id=raw_file.user_id)
            asset_dir = scope.asset_prefix(file_id=raw_file.id, filename=raw_file.filename).rstrip("/")

    cs = get_content_store()
    keys = run_store_sync(cs.list_prefix, asset_dir.rstrip("/") + "/", default=[]) or []
    rows: list[RawFileAsset] = []
    for index, key in enumerate(keys, start=1):
        rows.append(
            RawFileAsset(
                id=index,
                file_id=file_id,
                asset_name=key.rsplit("/", 1)[-1],
                storage_key=key,
                mime_type=mimetypes.guess_type(key)[0],
            )
        )
    return rows


def delete_raw_file_assets(session: Session, file_id: str) -> None:
    del session, file_id


def delete_raw_file(session: Session, raw_file: RawFile) -> None:
    if raw_file.id:
        unlink_all_courses_for_raw_file(session, file_id=raw_file.id)
    session.delete(raw_file)
    session.commit()
