"""File deletion use cases."""

from __future__ import annotations

from sqlmodel import Session

from app.shared.infra.exceptions import RawFileInUseError
from app.shared.infra.storage import get_content_store
from app.repositories.files_repo import delete_raw_file, list_linked_subjects_for_raw_file, unlink_raw_files_from_subject
from app.schemas.files import FileDeleteData
from app.utils.presenters import require_id
from app.workflows.ingest.intake.catalog import get_subject_files_or_raise, get_user_files_or_raise


async def delete_files(
    session: Session,
    *,
    subject_id: str,
    owner_user_id: str,
    file_ids: list[str],
) -> FileDeleteData:
    raw_files = get_subject_files_or_raise(session, subject_id=subject_id, file_ids=file_ids)
    unlinked = unlink_raw_files_from_subject(
        session,
        owner_user_id=owner_user_id,
        subject_id=subject_id,
        raw_files=raw_files,
    )
    return FileDeleteData(deleted_file_ids=[require_id(item.id, "RawFile.id") for item in unlinked])


async def delete_user_files(
    session: Session,
    *,
    owner_user_id: str,
    file_ids: list[str],
) -> FileDeleteData:
    raw_files = get_user_files_or_raise(session, owner_user_id=owner_user_id, file_ids=file_ids)
    deleted_file_ids: list[str] = []
    content_store = get_content_store()

    for raw_file in raw_files:
        file_id = require_id(raw_file.id, "RawFile.id")
        linked_subjects = list_linked_subjects_for_raw_file(session, file_id=file_id)
        if linked_subjects:
            raise RawFileInUseError(
                file_id,
                [
                    {"subject_id": item.id, "name": item.name}
                    for item in linked_subjects
                ],
            )
        if raw_file.file_path:
            await content_store.delete(raw_file.file_path)
        if raw_file.markdown_path:
            await content_store.delete(raw_file.markdown_path)
        if raw_file.asset_dir:
            await content_store.delete_prefix(raw_file.asset_dir.rstrip("/") + "/")
        else:
            await content_store.delete_prefix(
                content_store.user_file_scope(user_id=owner_user_id).file_prefix(
                    file_id=file_id,
                    filename=raw_file.filename,
                )
            )

        delete_raw_file(session, raw_file)
        deleted_file_ids.append(file_id)

    return FileDeleteData(deleted_file_ids=deleted_file_ids)


__all__ = ["delete_files", "delete_user_files"]
