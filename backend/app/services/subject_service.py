from __future__ import annotations

from sqlmodel import Session

from app.core.exceptions import SubjectInUseError, SubjectRegistryNotFoundError
from app.models import Subject
from app.repositories.subject_repo import (
    create_subject,
    delete_subject,
    get_subject_by_slug,
    list_subjects,
    subject_has_content,
    update_subject,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.subject import SubjectDeleteData, SubjectItem
from app.services.presenters import require_id
from app.utils.subject import generate_subject_id, validate_subject_id


def _create_unique_subject_id(session: Session) -> str:
    while True:
        subject_id = generate_subject_id()
        if get_subject_by_slug(session, subject_id) is None:
            return subject_id


def _to_subject_item(subject: Subject) -> SubjectItem:
    return SubjectItem(
        id=require_id(subject.id, "Subject.id"),
        subject_id=subject.slug,
        name=subject.name,
        description=subject.description,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
    )


def create_subject_record(
    session: Session,
    *,
    name: str,
    description: str = "",
) -> SubjectItem:
    subject = create_subject(
        session,
        Subject(
            slug=_create_unique_subject_id(session),
            name=name.strip() or "Untitled Subject",
            description=description.strip(),
        ),
    )
    return _to_subject_item(subject)


def get_subject_record(session: Session, subject_id: str) -> Subject:
    normalized_subject_id = validate_subject_id(subject_id)
    subject = get_subject_by_slug(session, normalized_subject_id)
    if subject is None:
        raise SubjectRegistryNotFoundError(normalized_subject_id)
    return subject


def get_subject_detail(session: Session, subject_id: str) -> SubjectItem:
    return _to_subject_item(get_subject_record(session, subject_id))


def list_subject_records(
    session: Session,
    *,
    page: int,
    size: int,
) -> PaginatedData[SubjectItem]:
    items, total = list_subjects(session, limit=size, offset=(page - 1) * size)
    return build_paginated_data(
        items=[_to_subject_item(item) for item in items],
        page=page,
        size=size,
        total=total,
    )


def update_subject_record(
    session: Session,
    *,
    subject_id: str,
    name: str,
    description: str = "",
) -> SubjectItem:
    subject = get_subject_record(session, subject_id)
    updated = update_subject(
        session,
        subject,
        name=name.strip() or subject.name,
        description=description.strip(),
    )
    return _to_subject_item(updated)


def delete_subject_record(session: Session, *, subject_id: str) -> SubjectDeleteData:
    subject = get_subject_record(session, subject_id)
    if subject_has_content(session, subject.slug):
        raise SubjectInUseError(subject.slug)
    delete_subject(session, subject)
    return SubjectDeleteData(deleted=True, subject_id=subject.slug)
