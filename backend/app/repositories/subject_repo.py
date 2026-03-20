"""学科数据访问层。"""

from __future__ import annotations

from sqlmodel import Session, func, select

from app.models import ChatMessage, Document, Exam, RawFile, Subject, UserProfile
from app.utils.time import utcnow


def create_subject(session: Session, subject: Subject) -> Subject:
    """创建学科。"""

    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def get_subject_by_slug(session: Session, slug: str) -> Subject | None:
    """按标识查询学科。"""

    return session.exec(select(Subject).where(Subject.slug == slug)).first()


def list_subjects(session: Session, *, limit: int, offset: int) -> tuple[list[Subject], int]:
    """分页读取学科列表。"""

    total = session.exec(select(func.count()).select_from(Subject)).one()
    stmt = (
        select(Subject)
        .order_by(Subject.updated_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def update_subject(
    session: Session,
    subject: Subject,
    *,
    name: str,
    description: str,
) -> Subject:
    """更新学科。"""

    subject.name = name
    subject.description = description
    subject.updated_at = utcnow()
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def delete_subject(session: Session, subject: Subject) -> None:
    """删除学科。"""

    session.delete(subject)
    session.commit()


def subject_has_content(session: Session, slug: str) -> bool:
    """判断学科下是否还有内容。"""

    statements = [
        select(func.count()).select_from(RawFile).where(RawFile.subject == slug),
        select(func.count()).select_from(Document).where(Document.subject == slug),
        select(func.count()).select_from(Exam).where(Exam.subject == slug),
        select(func.count()).select_from(ChatMessage).where(ChatMessage.subject == slug),
        select(func.count()).select_from(UserProfile).where(UserProfile.subject == slug),
    ]
    return any(session.exec(stmt).one() > 0 for stmt in statements)
