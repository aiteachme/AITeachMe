"""Raw file data-access helpers."""

from __future__ import annotations

from typing import Iterable

from sqlmodel import Session, delete, func, select

from app.models import RawFile, RawFileAsset, Subject
from app.utils.time import utcnow

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
        .join(Subject, RawFile.subject_id == Subject.id)
        .where(Subject.slug == subject, RawFile.id.in_(file_ids))  # type: ignore[union-attr]
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_raw_files_by_uids(
    session: Session,
    subject: str,
    file_uids: list[str],
) -> list[RawFile]:
    if not file_uids:
        return []

    stmt = (
        select(RawFile)
        .join(Subject, RawFile.subject_id == Subject.id)
        .where(Subject.slug == subject, RawFile.uid.in_(file_uids))  # type: ignore[union-attr]
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
    filters = [Subject.slug == subject, RawFile.subject_id == Subject.id]
    if status:
        filters.append(RawFile.status == status)

    total = int(
        session.exec(
            select(func.count())
            .select_from(RawFile)
            .join(Subject, RawFile.subject_id == Subject.id)
            .where(*filters)
        ).one()
    )
    stmt = (
        select(RawFile)
        .join(Subject, RawFile.subject_id == Subject.id)
        .where(*filters)
        .order_by(RawFile.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def list_all_raw_files_by_subject(session: Session, subject: str) -> list[RawFile]:
    stmt = (
        select(RawFile)
        .join(Subject, RawFile.subject_id == Subject.id)
        .where(Subject.slug == subject)
        .order_by(RawFile.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def update_raw_file(
    session: Session,
    raw_file: RawFile,
    *,
    parsed_markdown: str | object = _UNSET,
    parser_used: str | None | object = _UNSET,
    parse_metadata_json: str | object = _UNSET,
    parse_error_message: str | None | object = _UNSET,
    classification_json: str | object = _UNSET,
    quality_score: float | None | object = _UNSET,
    image_count: int | object = _UNSET,
    status: str | None = None,
    ingest_status: str | object = _UNSET,
    digest_current_step: str | None | object = _UNSET,
    mime_type: str | None | object = _UNSET,
    storage_key: str | object = _UNSET,
    size_bytes: int | None | object = _UNSET,
    checksum_sha256: str | None | object = _UNSET,
    estimated_pages: int | None | object = _UNSET,
    detected_language: str | None | object = _UNSET,
) -> RawFile:
    if parsed_markdown is not _UNSET:
        raw_file.parsed_markdown = str(parsed_markdown)
    if parser_used is not _UNSET:
        raw_file.parser_used = parser_used
    if parse_metadata_json is not _UNSET:
        raw_file.parse_metadata_json = str(parse_metadata_json)
    if parse_error_message is not _UNSET:
        raw_file.parse_error_message = parse_error_message
    if classification_json is not _UNSET:
        raw_file.classification_json = str(classification_json)
    if quality_score is not _UNSET:
        raw_file.quality_score = quality_score
    if image_count is not _UNSET:
        raw_file.image_count = int(image_count)
    if status is not None:
        raw_file.status = status
    if ingest_status is not _UNSET:
        raw_file.ingest_status = str(ingest_status)
    if digest_current_step is not _UNSET:
        raw_file.digest_current_step = digest_current_step
    if mime_type is not _UNSET:
        raw_file.mime_type = mime_type
    if storage_key is not _UNSET:
        raw_file.storage_key = str(storage_key)
    if size_bytes is not _UNSET:
        raw_file.size_bytes = size_bytes
    if checksum_sha256 is not _UNSET:
        raw_file.checksum_sha256 = checksum_sha256
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
    raw_file_id: int,
    assets: Iterable[RawFileAsset],
) -> list[RawFileAsset]:
    session.exec(delete(RawFileAsset).where(RawFileAsset.raw_file_id == raw_file_id))
    persisted: list[RawFileAsset] = []
    for asset in assets:
        session.add(asset)
        persisted.append(asset)
    session.commit()
    for asset in persisted:
        session.refresh(asset)
    return persisted


def list_assets_by_raw_file_id(session: Session, raw_file_id: int) -> list[RawFileAsset]:
    stmt = (
        select(RawFileAsset)
        .where(RawFileAsset.raw_file_id == raw_file_id)
        .order_by(RawFileAsset.page_num.asc(), RawFileAsset.asset_name.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def delete_raw_file_assets(session: Session, raw_file_id: int) -> None:
    session.exec(delete(RawFileAsset).where(RawFileAsset.raw_file_id == raw_file_id))
    session.commit()


def delete_raw_file(session: Session, raw_file: RawFile) -> None:
    delete_raw_file_assets(session, raw_file_id=int(raw_file.id or 0))
    session.delete(raw_file)
    session.commit()
