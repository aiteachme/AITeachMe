"""
RawFile CRUD — 文件摄入相关数据访问

需求：5.2, 5.10, 5.11
"""

from sqlmodel import Session, select, func

from app.repositories.models import RawFile


def create_raw_file(session: Session, raw_file: RawFile) -> RawFile:
    """创建 RawFile 记录。"""
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def get_raw_file_by_id(session: Session, raw_file_id: int) -> RawFile | None:
    """按 id 查询 RawFile。"""
    return session.get(RawFile, raw_file_id)


def update_parse_status(
    session: Session, raw_file_id: int, status: str
) -> RawFile | None:
    """更新 RawFile 的 parse_status。"""
    raw_file = session.get(RawFile, raw_file_id)
    if raw_file is None:
        return None
    raw_file.parse_status = status
    session.add(raw_file)
    session.commit()
    session.refresh(raw_file)
    return raw_file


def delete_raw_file(session: Session, raw_file_id: int) -> bool:
    """删除 RawFile 记录（上传失败回滚用）。"""
    raw_file = session.get(RawFile, raw_file_id)
    if raw_file is None:
        return False
    session.delete(raw_file)
    session.commit()
    return True


def list_raw_files_by_subject(
    session: Session, subject: str, *, limit: int = 100, offset: int = 0
) -> tuple[list[RawFile], int]:
    """按学科分页列表 RawFile，返回 (items, total)。"""
    count_stmt = select(func.count()).select_from(RawFile).where(RawFile.subject == subject)
    total = session.exec(count_stmt).one()

    stmt = (
        select(RawFile)
        .where(RawFile.subject == subject)
        .order_by(RawFile.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    items = list(session.exec(stmt).all())
    return items, total
