from __future__ import annotations

from sqlmodel import Session, func, select

from app.models import Subject
from app.utils.time import utcnow


def create_subject(session: Session, subject: Subject) -> Subject:
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def get_subject_by_slug(session: Session, slug: str, *, owner_user_id: str | None = None) -> Subject | None:
    stmt = select(Subject).where(Subject.slug == slug)
    if owner_user_id is not None:
        stmt = stmt.where(Subject.user_id == owner_user_id)
    return session.exec(stmt).first()


def list_subjects(
    session: Session,
    *,
    owner_user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[Subject], int]:
    total = int(
        session.exec(
            select(func.count())
            .select_from(Subject)
            .where(Subject.user_id == owner_user_id)
        ).one()
    )
    items = list(
        session.exec(
            select(Subject)
            .where(Subject.user_id == owner_user_id)
            .order_by(Subject.created_at.desc(), Subject.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return items, total


def update_subject(
    session: Session,
    subject: Subject,
    *,
    name: str | None = None,
    description: str | None = None,
    user_intent: str | None = None,
) -> Subject:
    if name is not None:
        subject.name = name or subject.name
    if description is not None:
        subject.description = description
    if user_intent is not None:
        subject.user_intent = user_intent
    subject.updated_at = utcnow()
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def save_subject(session: Session, subject: Subject) -> Subject:
    subject.updated_at = utcnow()
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def delete_subject(session: Session, subject: Subject) -> None:
    session.delete(subject)
    session.commit()
