"""Course catalog use cases."""

from __future__ import annotations

from sqlmodel import Session

from app.shared.infra.exceptions import CourseRegistryNotFoundError
from app.models import Course
from app.repositories.course_repo import (
    create_course,
    get_course_by_id,
    list_courses,
    save_course,
    update_course,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.course import CourseItem
from app.utils.course import generate_course_id, validate_course_id
from app.workflows.support.courses.icons import get_course_icon_key, set_course_icon_key


def _create_unique_course_id(session: Session) -> str:
    while True:
        course_id = generate_course_id()
        if get_course_by_id(session, course_id) is None:
            return course_id


def _to_course_item(course: Course) -> CourseItem:
    return CourseItem(
        course_id=course.id,
        name=course.name,
        description=course.description,
        user_intent=course.user_intent,
        icon_key=get_course_icon_key(course),
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


def create_course_record(
    session: Session,
    *,
    owner_user_id: str,
    name: str,
    description: str = "",
    user_intent: str = "",
    icon_key: str | None = None,
) -> CourseItem:
    course = Course(
        id=_create_unique_course_id(session),
        user_id=owner_user_id,
        name=name.strip(),
        description=description.strip(),
        user_intent=user_intent.strip(),
    )
    if icon_key:
        set_course_icon_key(course, icon_key)
    course = create_course(session, course)
    return _to_course_item(course)


def get_course_record(
    session: Session,
    course_id: str,
    *,
    owner_user_id: str,
) -> Course:
    normalized_course_id = validate_course_id(course_id)
    course = get_course_by_id(
        session,
        normalized_course_id,
        owner_user_id=owner_user_id,
    )
    if course is None:
        raise CourseRegistryNotFoundError(normalized_course_id)
    return course


def get_course_detail(
    session: Session,
    course_id: str,
    *,
    owner_user_id: str,
) -> CourseItem:
    return _to_course_item(get_course_record(session, course_id, owner_user_id=owner_user_id))


def list_course_records(
    session: Session,
    *,
    owner_user_id: str,
    page: int,
    size: int,
) -> PaginatedData[CourseItem]:
    items, total = list_courses(
        session,
        owner_user_id=owner_user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[_to_course_item(item) for item in items],
        page=page,
        size=size,
        total=total,
    )


def update_course_record(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str,
    name: str | None = None,
    description: str | None = None,
    user_intent: str | None = None,
    icon_key: str | None = None,
) -> CourseItem:
    course = get_course_record(session, course_id, owner_user_id=owner_user_id)
    updated = update_course(
        session,
        course,
        name=name.strip() if name is not None else None,
        description=description.strip() if description is not None else None,
        user_intent=user_intent.strip() if user_intent is not None else None,
    )
    if icon_key:
        set_course_icon_key(updated, icon_key)
        updated = save_course(session, updated)
    return _to_course_item(updated)


__all__ = [
    "create_course_record",
    "get_course_detail",
    "get_course_record",
    "list_course_records",
    "update_course_record",
]
