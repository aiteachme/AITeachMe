from __future__ import annotations

from sqlmodel import Session, func, select

from app.models import Subject
from app.utils.time import utcnow


def create_subject(session: Session, subject: Subject) -> Subject:
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def get_subject_by_slug(session: Session, slug: str) -> Subject | None:
    return session.exec(select(Subject).where(Subject.slug == slug)).first()


def list_subjects(session: Session, *, limit: int, offset: int) -> tuple[list[Subject], int]:
    total = int(session.exec(select(func.count()).select_from(Subject)).one())
    items = list(
        session.exec(
            select(Subject)
            .order_by(Subject.updated_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return items, total


def update_subject(
    session: Session,
    subject: Subject,
    *,
    name: str,
    description: str,
) -> Subject:
    subject.name = name
    subject.description = description
    subject.updated_at = utcnow()
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def delete_subject(session: Session, subject: Subject) -> None:
    session.delete(subject)
    session.commit()
