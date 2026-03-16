"""Top-level subject registry orchestration helpers."""

from __future__ import annotations

from sqlmodel import Session

from app.core.exceptions import SubjectAlreadyExistsError, SubjectInUseError, SubjectRegistryNotFoundError
from app.repositories.models import Subject
from app.repositories.subject_repo import (
    create_subject,
    delete_subject,
    get_subject_by_slug,
    list_subjects,
    subject_has_content,
    update_subject,
)
from app.utils.subject import validate_subject


def normalize_subject_slug(subject: str) -> str:
    """Centralized subject slug normalization for future terminology changes."""

    return validate_subject(subject)


def create_subject_record(
    session: Session,
    *,
    slug: str,
    name: str,
    description: str = "",
) -> Subject:
    normalized_slug = normalize_subject_slug(slug)
    if get_subject_by_slug(session, normalized_slug) is not None:
        raise SubjectAlreadyExistsError(normalized_slug)

    subject = Subject(
        slug=normalized_slug,
        name=name.strip() or normalized_slug,
        description=description.strip(),
    )
    return create_subject(session, subject)


def get_subject_record(session: Session, slug: str) -> Subject:
    normalized_slug = normalize_subject_slug(slug)
    subject = get_subject_by_slug(session, normalized_slug)
    if subject is None:
        raise SubjectRegistryNotFoundError(normalized_slug)
    return subject


def list_subject_records(session: Session, *, limit: int = 100, offset: int = 0) -> tuple[list[Subject], int]:
    return list_subjects(session, limit=limit, offset=offset)


def update_subject_record(
    session: Session,
    *,
    slug: str,
    name: str,
    description: str = "",
) -> Subject:
    subject = get_subject_record(session, slug)
    return update_subject(
        session,
        subject,
        name=name.strip() or subject.name,
        description=description.strip(),
    )


def delete_subject_record(session: Session, *, slug: str) -> None:
    subject = get_subject_record(session, slug)
    if subject_has_content(session, subject.slug):
        raise SubjectInUseError(subject.slug)
    delete_subject(session, subject)
