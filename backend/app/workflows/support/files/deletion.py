"""File deletion use cases."""

from __future__ import annotations

from sqlmodel import Session

from app.shared.infra.storage import get_content_store
from app.repositories.files_repo import delete_raw_file
from app.schemas.files import FileDeleteData
from app.utils.presenters import require_id, require_uid
from app.workflows.support.files.catalog import get_subject_files_by_uid_or_raise


async def delete_files(
    session: Session,
    *,
    subject: str,
    owner_user_id: str,
    file_uids: list[str],
) -> FileDeleteData:
    raw_files = get_subject_files_by_uid_or_raise(session, subject=subject, file_uids=file_uids)
    deleted_uids: list[str] = []
    content_store = get_content_store()
    subject_scope = content_store.subject_scope(user_id=owner_user_id, subject=subject)

    for raw_file in raw_files:
        raw_file_uid = require_uid(raw_file.uid, "RawFile.uid")
        raw_file_id = require_id(raw_file.id, "RawFile.id")

        if raw_file.file_path:
            await content_store.delete(raw_file.file_path)
        if raw_file.markdown_path:
            await content_store.delete(raw_file.markdown_path)
        await content_store.delete_prefix(subject_scope.asset_prefix(raw_file_id))

        delete_raw_file(session, raw_file)
        deleted_uids.append(raw_file_uid)

    return FileDeleteData(deleted_file_uids=deleted_uids)


__all__ = ["delete_files"]
