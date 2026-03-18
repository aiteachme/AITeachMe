"""原始文件数据访问层。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, func, select

from app.models import RawFile

_UNSET = object()


def create_raw_file(session: Session, raw_file: RawFile) -> RawFile:
    """创建原始文件记录。"""

    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def get_raw_file_by_id(session: Session, raw_file_id: int) -> RawFile | None:
    """按 ID 查询文件。"""

    return session.get(RawFile, raw_file_id)


def list_raw_files_by_ids(
    session: Session,
    subject: str,
    file_ids: list[int],
) -> list[RawFile]:
    """按 ID 列表批量查询文件。"""

    if not file_ids:
        return []

    stmt = (
        select(RawFile)
        .where(RawFile.subject == subject, RawFile.id.in_(file_ids))  # type: ignore[union-attr]
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
    """分页查询学科下的文件。"""

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


def update_raw_file(
    session: Session,
    raw_file: RawFile,
    *,
    file_path: str | None | object = _UNSET,
    markdown_path: str | None | object = _UNSET,
    asset_dir: str | None | object = _UNSET,
    status: str | None = None,
    error_message: str | None | object = _UNSET,
) -> RawFile:
    """更新原始文件记录。"""

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
    raw_file.updated_at = datetime.utcnow()
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def delete_raw_file(session: Session, raw_file: RawFile) -> None:
    """删除原始文件记录。"""

    session.delete(raw_file)
    session.commit()
