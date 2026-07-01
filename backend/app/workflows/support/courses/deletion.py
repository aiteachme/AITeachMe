"""Course deletion use cases."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.shared.infra.exceptions import CourseInUseError
from app.models import Course
from app.schemas.course import CourseDeleteData, CourseDeletePreviewData
from app.workflows.support.courses.catalog import get_course_record
from app.workflows.support.courses.lib.deletion import (
    build_course_delete_preview,
    collect_course_delete_counts,
    delete_course_artifacts_async,
    delete_course_with_all_content,
)


def preview_course_delete(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str,
) -> CourseDeletePreviewData:
    course = get_course_record(session, course_id, owner_user_id=owner_user_id)
    return build_course_delete_preview(session, course=course)


async def delete_course_record(
    session: Session,
    *,
    owner_user_id: str,
    course_id: str,
    force: bool = False,
    known_detail_counts: dict[str, int] | None = None,
    background_task_registry: Any | None = None,
) -> CourseDeleteData:
    course = get_course_record(session, course_id, owner_user_id=owner_user_id)
    if force and known_detail_counts is not None:
        detail_counts = _normalize_known_detail_counts(known_detail_counts)
    else:
        preview = build_course_delete_preview(session, course=course)
        if preview.has_content and not force:
            raise CourseInUseError(course.id)
        detail_counts = preview.detail_counts
    await _cancel_course_background_work(
        session,
        course=course,
        owner_user_id=owner_user_id,
        background_task_registry=background_task_registry,
    )
    deleted_counts = (
        delete_course_with_all_content(
            session,
            course=course,
            background_task_registry=background_task_registry,
            counts=detail_counts,
        )
        if force
        else _delete_empty_course(
            session,
            course,
            background_task_registry=background_task_registry,
            counts=detail_counts,
        )
    )
    return CourseDeleteData(
        deleted=True,
        course_id=course.id,
        deleted_counts=deleted_counts,
    )


def _normalize_known_detail_counts(counts: dict[str, int]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, value in counts.items():
        try:
            normalized[str(key)] = max(0, int(value))
        except (TypeError, ValueError):
            normalized[str(key)] = 0
    return normalized


def _delete_empty_course(
    session: Session,
    course: Course,
    *,
    background_task_registry: Any | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, int]:
    return delete_course_with_all_content(
        session,
        course=course,
        background_task_registry=background_task_registry,
        counts=counts,
    )


async def _cancel_course_background_work(
    session: Session,
    *,
    course: Course,
    owner_user_id: str,
    background_task_registry: Any | None,
) -> None:
    try:
        from app.workflows.digest.common.build_lifecycle import cancel_knowledge_build

        await cancel_knowledge_build(
            session,
            course=course,
            user_id=owner_user_id,
            background_task_registry=background_task_registry,
        )
    except Exception:
        # Deletion must still proceed; stale runtime/tasks are best-effort cleanup.
        pass

    if background_task_registry is None:
        return
    try:
        await background_task_registry.cancel_matching(course_id=course.id)
    except Exception:
        pass


__all__ = [
    "build_course_delete_preview",
    "collect_course_delete_counts",
    "delete_course_artifacts_async",
    "delete_course_record",
    "delete_course_with_all_content",
    "preview_course_delete",
]
