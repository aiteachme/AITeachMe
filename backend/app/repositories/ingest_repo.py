"""Persistence helpers for raw uploaded files and parsed-file metadata."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, func, select

from app.repositories.models import RawFile

_UNSET = object()


def create_raw_file(session: Session, raw_file: RawFile) -> RawFile:
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def get_raw_file_by_id(session: Session, raw_file_id: int) -> RawFile | None:
    return session.get(RawFile, raw_file_id)


def list_raw_files_by_ids(
    session: Session,
    subject: str,
    file_ids: list[int],
) -> list[RawFile]:
    if not file_ids:
        return []

    stmt = (
        select(RawFile)
        .where(RawFile.subject == subject, RawFile.id.in_(file_ids))  # type: ignore[union-attr]
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def update_raw_file(
    session: Session,
    raw_file: RawFile,
    *,
    file_path: str | None | object = _UNSET,
    markdown_path: str | None | object = _UNSET,
    asset_dir: str | None | object = _UNSET,
    parse_status: str | None = None,
    parse_error: str | None = None,
) -> RawFile:
    if file_path is not _UNSET:
        raw_file.file_path = file_path
    if markdown_path is not _UNSET:
        raw_file.markdown_path = markdown_path
    if asset_dir is not _UNSET:
        raw_file.asset_dir = asset_dir
    if parse_status is not None:
        raw_file.parse_status = parse_status
    raw_file.parse_error = parse_error
    raw_file.updated_at = datetime.utcnow()
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def delete_raw_file(session: Session, raw_file_id: int) -> bool:
    raw_file = session.get(RawFile, raw_file_id)
    if raw_file is None:
        return False
    session.delete(raw_file)
    session.commit()
    return True


def list_raw_files_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int = 100,
    offset: int = 0,
    parse_status: str | None = None,
) -> tuple[list[RawFile], int]:
    filters = [RawFile.subject == subject]
    if parse_status:
        filters.append(RawFile.parse_status == parse_status)

    count_stmt = select(func.count()).select_from(RawFile).where(*filters)
    total = session.exec(count_stmt).one()

    stmt = (
        select(RawFile)
        .where(*filters)
        .order_by(RawFile.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    items = list(session.exec(stmt).all())
    return items, total
