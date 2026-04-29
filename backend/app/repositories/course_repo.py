from __future__ import annotations

from sqlmodel import Session, func, select

from app.models import Course
from app.utils.time import utcnow


def create_course(session: Session, course: Course) -> Course:
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def get_course_by_id(session: Session, course_id: str, *, owner_user_id: str | None = None) -> Course | None:
    stmt = select(Course).where(Course.id == course_id)
    if owner_user_id is not None:
        stmt = stmt.where(Course.user_id == owner_user_id)
    return session.exec(stmt).first()


def list_courses(
    session: Session,
    *,
    owner_user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[Course], int]:
    total = int(
        session.exec(
            select(func.count())
            .select_from(Course)
            .where(Course.user_id == owner_user_id)
        ).one()
    )
    items = list(
        session.exec(
            select(Course)
            .where(Course.user_id == owner_user_id)
            .order_by(Course.created_at.desc(), Course.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return items, total


def update_course(
    session: Session,
    course: Course,
    *,
    name: str | None = None,
    description: str | None = None,
    user_intent: str | None = None,
) -> Course:
    if name is not None:
        course.name = name or course.name
    if description is not None:
        course.description = description
    if user_intent is not None:
        course.user_intent = user_intent
    course.updated_at = utcnow()
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def save_course(session: Session, course: Course) -> Course:
    course.updated_at = utcnow()
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def delete_course(session: Session, course: Course) -> None:
    session.delete(course)
    session.commit()
