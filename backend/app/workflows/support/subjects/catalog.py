"""Subject catalog use cases."""

from __future__ import annotations

from sqlmodel import Session

from app.shared.infra.exceptions import SubjectRegistryNotFoundError
from app.models import Subject
from app.repositories.subject_repo import (
    create_subject,
    get_subject_by_slug,
    list_subjects,
    update_subject,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.subject import SubjectItem
from app.utils.presenters import require_id
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
        created_at=subject.created_at,
        updated_at=subject.updated_at,
    )


def create_subject_record(
    session: Session,
    *,
    owner_user_id: str,
    name: str,
) -> SubjectItem:
    subject = create_subject(
        session,
        Subject(
            user_id=owner_user_id,
            slug=_create_unique_subject_id(session),
            name=name.strip(),
        ),
    )
    return _to_subject_item(subject)


def get_subject_record(
    session: Session,
    subject_id: str,
    *,
    owner_user_id: str,
) -> Subject:
    normalized_subject_id = validate_subject_id(subject_id)
    subject = get_subject_by_slug(
        session,
        normalized_subject_id,
        owner_user_id=owner_user_id,
    )
    if subject is None:
        raise SubjectRegistryNotFoundError(normalized_subject_id)
    return subject


def get_subject_detail(
    session: Session,
    subject_id: str,
    *,
    owner_user_id: str,
) -> SubjectItem:
    return _to_subject_item(get_subject_record(session, subject_id, owner_user_id=owner_user_id))


def list_subject_records(
    session: Session,
    *,
    owner_user_id: str,
    page: int,
    size: int,
) -> PaginatedData[SubjectItem]:
    items, total = list_subjects(
        session,
        owner_user_id=owner_user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[_to_subject_item(item) for item in items],
        page=page,
        size=size,
        total=total,
    )


def update_subject_record(
    session: Session,
    *,
    owner_user_id: str,
    subject_id: str,
    name: str,
) -> SubjectItem:
    subject = get_subject_record(session, subject_id, owner_user_id=owner_user_id)
    updated = update_subject(
        session,
        subject,
        name=name.strip() or subject.name,
    )
    return _to_subject_item(updated)


__all__ = [
    "create_subject_record",
    "get_subject_detail",
    "get_subject_record",
    "list_subject_records",
    "update_subject_record",
]
