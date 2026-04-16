"""Subject deletion use cases."""

from __future__ import annotations

from sqlmodel import Session

from app.shared.infra.exceptions import SubjectInUseError
from app.models import Subject
from app.repositories.subject_repo import delete_subject
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
) -> SubjectDeleteData:
    subject = get_subject_record(session, subject_id, owner_user_id=owner_user_id)
    preview = build_subject_delete_preview(session, subject=subject)
    if preview.has_content and not force:
        raise SubjectInUseError(subject.slug)
    deleted_counts = (
        delete_subject_with_all_content(session, subject=subject)
        if force
        else _delete_empty_subject(session, subject)
    )
    return SubjectDeleteData(
        deleted=True,
        subject_id=subject.slug,
        deleted_counts=deleted_counts,
    )


def _delete_empty_subject(session: Session, subject: Subject) -> dict[str, int]:
    delete_subject(session, subject)
    return {"subject": 1}


__all__ = [
    "build_subject_delete_preview",
    "collect_subject_delete_counts",
    "delete_subject_artifacts_async",
    "delete_subject_record",
    "delete_subject_with_all_content",
    "preview_subject_delete",
]
