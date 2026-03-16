"""Top-level subject registry persistence helpers."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, func, select

from app.repositories.models import (
    ChatMessage,
    DocSet,
    Document,
    Exam,
    RawFile,
    Subject,
    UserProfile,
)


def create_subject(session: Session, subject: Subject) -> Subject:
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def get_subject_by_slug(session: Session, slug: str) -> Subject | None:
    stmt = select(Subject).where(Subject.slug == slug)
    return session.exec(stmt).first()


def list_subjects(session: Session, *, limit: int = 100, offset: int = 0) -> tuple[list[Subject], int]:
    count_stmt = select(func.count()).select_from(Subject)
    total = session.exec(count_stmt).one()

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
    subject.name = name
    subject.description = description
    subject.updated_at = datetime.utcnow()
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def delete_subject(session: Session, subject: Subject) -> None:
    session.delete(subject)
    session.commit()


def subject_has_content(session: Session, slug: str) -> bool:
    statements = [
        select(func.count()).select_from(RawFile).where(RawFile.subject == slug),
        select(func.count()).select_from(DocSet).where(DocSet.subject == slug),
        select(func.count()).select_from(Document).where(Document.subject == slug),
        select(func.count()).select_from(Exam).where(Exam.subject == slug),
        select(func.count()).select_from(ChatMessage).where(ChatMessage.subject == slug),
        select(func.count()).select_from(UserProfile).where(UserProfile.subject == slug),
    ]
    return any(session.exec(stmt).one() > 0 for stmt in statements)
