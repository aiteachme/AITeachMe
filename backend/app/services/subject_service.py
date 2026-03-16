"""学科服务层。"""

from __future__ import annotations

from sqlmodel import Session

from app.core.exceptions import SubjectAlreadyExistsError, SubjectInUseError, SubjectRegistryNotFoundError
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
from app.utils.subject import validate_subject


def normalize_subject_slug(subject: str) -> str:
    """统一处理学科标识。"""

    return validate_subject(subject)


def _to_subject_item(subject: Subject) -> SubjectItem:
    return SubjectItem(
        id=require_id(subject.id, "Subject.id"),
        subject=subject.slug,
        name=subject.name,
        description=subject.description,
        created_at=subject.created_at,
        updated_at=subject.updated_at,
    )


def create_subject_record(
    session: Session,
    *,
    slug: str,
    name: str,
    description: str = "",
) -> SubjectItem:
    """创建学科。"""

    normalized_slug = normalize_subject_slug(slug)
    if get_subject_by_slug(session, normalized_slug) is not None:
        raise SubjectAlreadyExistsError(normalized_slug)

    subject = create_subject(
        session,
        Subject(
            slug=normalized_slug,
            name=name.strip() or normalized_slug,
            description=description.strip(),
        ),
    )
    return _to_subject_item(subject)


def get_subject_record(session: Session, slug: str) -> Subject:
    """读取学科原始模型。"""

    normalized_slug = normalize_subject_slug(slug)
    subject = get_subject_by_slug(session, normalized_slug)
    if subject is None:
        raise SubjectRegistryNotFoundError(normalized_slug)
    return subject


def get_subject_detail(session: Session, slug: str) -> SubjectItem:
    """读取学科详情。"""

    return _to_subject_item(get_subject_record(session, slug))


def list_subject_records(
    session: Session,
    *,
    page: int,
    size: int,
) -> PaginatedData[SubjectItem]:
    """分页读取学科列表。"""

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
    slug: str,
    name: str,
    description: str = "",
) -> SubjectItem:
    """更新学科。"""

    subject = get_subject_record(session, slug)
    updated = update_subject(
        session,
        subject,
        name=name.strip() or subject.name,
        description=description.strip(),
    )
    return _to_subject_item(updated)


def delete_subject_record(session: Session, *, slug: str) -> SubjectDeleteData:
    """删除学科。"""

    subject = get_subject_record(session, slug)
    if subject_has_content(session, subject.slug):
        raise SubjectInUseError(subject.slug)
    delete_subject(session, subject)
    return SubjectDeleteData(deleted=True, subject=subject.slug)
