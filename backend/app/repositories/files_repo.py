"""Raw file data-access helpers."""

from __future__ import annotations

from sqlmodel import Session, func, select

from app.models import RawFile
from app.utils.time import utcnow

_UNSET = object()


def create_raw_file(session: Session, raw_file: RawFile) -> RawFile:
    """Persist one raw file row."""

    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def get_raw_file_by_id(session: Session, raw_file_id: int) -> RawFile | None:
    """Load one raw file by internal ID."""

    return session.get(RawFile, raw_file_id)


def get_raw_file_by_uid(session: Session, raw_file_uid: str) -> RawFile | None:
    """Load one raw file by public UID."""

    stmt = select(RawFile).where(RawFile.uid == raw_file_uid)
    return session.exec(stmt).first()


def list_raw_files_by_ids(
    session: Session,
    subject: str,
    file_ids: list[int],
) -> list[RawFile]:
    """Batch load files by internal IDs."""

    if not file_ids:
        return []

    stmt = (
        select(RawFile)
        .where(RawFile.subject == subject, RawFile.id.in_(file_ids))  # type: ignore[union-attr]
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_raw_files_by_uids(
    session: Session,
    subject: str,
    file_uids: list[str],
) -> list[RawFile]:
    """Batch load files by public UIDs."""

    if not file_uids:
        return []

    stmt = (
        select(RawFile)
        .where(RawFile.subject == subject, RawFile.uid.in_(file_uids))  # type: ignore[union-attr]
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_raw_files_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
    status: str | None = None,
) -> tuple[list[RawFile], int]:
    """Paginate files under one subject."""

    filters = [RawFile.subject == subject]
    if status:
        filters.append(RawFile.status == status)

    total = session.exec(select(func.count()).select_from(RawFile).where(*filters)).one()
    stmt = (
        select(RawFile)
        .where(*filters)
        .order_by(RawFile.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def list_all_raw_files_by_subject(session: Session, subject: str) -> list[RawFile]:
    """Load every file under one subject."""

    stmt = (
        select(RawFile)
        .where(RawFile.subject == subject)
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
    status: str | None = None,
    error_message: str | None | object = _UNSET,
    content_hash: str | None | object = _UNSET,
    file_size_bytes: int | None | object = _UNSET,
    estimated_pages: int | None | object = _UNSET,
    detected_language: str | None | object = _UNSET,
    classification_result: str | None | object = _UNSET,
    quality_score: float | None | object = _UNSET,
    parse_metadata: str | None | object = _UNSET,
    image_count: int | None | object = _UNSET,
    ingest_status: str | None | object = _UNSET,
) -> RawFile:
    """Update one raw file row."""

    if file_path is not _UNSET:
        raw_file.file_path = file_path
    if markdown_path is not _UNSET:
        raw_file.markdown_path = markdown_path
    if asset_dir is not _UNSET:
        raw_file.asset_dir = asset_dir
    if status is not None:
        raw_file.status = status
    if error_message is not _UNSET:
        raw_file.error_message = error_message
    if content_hash is not _UNSET:
        raw_file.content_hash = content_hash
    if file_size_bytes is not _UNSET:
        raw_file.file_size_bytes = file_size_bytes
    if estimated_pages is not _UNSET:
        raw_file.estimated_pages = estimated_pages
    if detected_language is not _UNSET:
        raw_file.detected_language = detected_language
    if classification_result is not _UNSET:
        raw_file.classification_result = classification_result
    if quality_score is not _UNSET:
        raw_file.quality_score = quality_score
    if parse_metadata is not _UNSET:
        raw_file.parse_metadata = parse_metadata
    if image_count is not _UNSET:
        raw_file.image_count = image_count
    if ingest_status is not _UNSET:
        raw_file.ingest_status = ingest_status
    raw_file.updated_at = utcnow()
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def delete_raw_file(session: Session, raw_file: RawFile) -> None:
    """Delete one raw file row."""

    session.delete(raw_file)
    session.commit()
