"""Subject deletion use cases."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.shared.infra.exceptions import SubjectInUseError
from app.models import Subject
from app.schemas.subject import SubjectDeleteData, SubjectDeletePreviewData
from app.workflows.support.subjects.catalog import get_subject_record
from app.workflows.support.subjects.lib.deletion import (
    build_subject_delete_preview,
    collect_subject_delete_counts,
    delete_subject_artifacts_async,
    delete_subject_with_all_content,
)


def preview_subject_delete(
    session: Session,
    *,
    owner_user_id: str,
    subject_id: str,
) -> SubjectDeletePreviewData:
    subject = get_subject_record(session, subject_id, owner_user_id=owner_user_id)
    return build_subject_delete_preview(session, subject=subject)


def delete_subject_record(
    session: Session,
    *,
    owner_user_id: str,
    subject_id: str,
    force: bool = False,
    known_detail_counts: dict[str, int] | None = None,
    background_task_registry: Any | None = None,
) -> SubjectDeleteData:
    subject = get_subject_record(session, subject_id, owner_user_id=owner_user_id)
    if force and known_detail_counts is not None:
        detail_counts = _normalize_known_detail_counts(known_detail_counts)
    else:
        preview = build_subject_delete_preview(session, subject=subject)
        if preview.has_content and not force:
            raise SubjectInUseError(subject.id)
        detail_counts = preview.detail_counts
    deleted_counts = (
        delete_subject_with_all_content(
            session,
            subject=subject,
            background_task_registry=background_task_registry,
            counts=detail_counts,
        )
        if force
        else _delete_empty_subject(
            session,
            subject,
            background_task_registry=background_task_registry,
            counts=detail_counts,
        )
    )
    return SubjectDeleteData(
        deleted=True,
        subject_id=subject.id,
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


def _delete_empty_subject(
    session: Session,
    subject: Subject,
    *,
    background_task_registry: Any | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, int]:
    return delete_subject_with_all_content(
        session,
        subject=subject,
        background_task_registry=background_task_registry,
        counts=counts,
    )


__all__ = [
    "build_subject_delete_preview",
    "collect_subject_delete_counts",
    "delete_subject_artifacts_async",
    "delete_subject_record",
    "delete_subject_with_all_content",
    "preview_subject_delete",
]
