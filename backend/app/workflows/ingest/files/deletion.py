"""File deletion use cases."""

from __future__ import annotations

from sqlmodel import Session

from app.shared.infra.storage import get_content_store
from app.repositories.files_repo import delete_raw_file, unlink_raw_files_from_subject
from app.schemas.files import FileDeleteData
from app.utils.presenters import require_uid
from app.workflows.ingest.files.catalog import get_subject_files_by_uid_or_raise, get_user_files_by_uid_or_raise


async def delete_files(
    session: Session,
    *,
    subject: str,
    owner_user_id: str,
    file_uids: list[str],
) -> FileDeleteData:
    raw_files = get_subject_files_by_uid_or_raise(session, subject=subject, file_uids=file_uids)
    unlinked = unlink_raw_files_from_subject(
        session,
        owner_user_id=owner_user_id,
        subject=subject,
        raw_files=raw_files,
    )
    return FileDeleteData(deleted_file_uids=[require_uid(item.uid, "RawFile.uid") for item in unlinked])


async def delete_user_files(
    session: Session,
    *,
    owner_user_id: str,
    file_uids: list[str],
) -> FileDeleteData:
    raw_files = get_user_files_by_uid_or_raise(session, owner_user_id=owner_user_id, file_uids=file_uids)
    deleted_uids: list[str] = []
    content_store = get_content_store()

    for raw_file in raw_files:
        raw_file_uid = require_uid(raw_file.uid, "RawFile.uid")
        if raw_file.file_path:
            await content_store.delete(raw_file.file_path)
        if raw_file.markdown_path:
            await content_store.delete(raw_file.markdown_path)
        if raw_file.asset_dir:
            await content_store.delete_prefix(raw_file.asset_dir.rstrip("/") + "/")
        else:
            await content_store.delete_prefix(
                content_store.user_file_scope(user_id=owner_user_id).file_prefix(
                    file_uid=raw_file_uid,
                    filename=raw_file.filename,
                )
            )

        delete_raw_file(session, raw_file)
        deleted_uids.append(raw_file_uid)

    return FileDeleteData(deleted_file_uids=deleted_uids)


__all__ = ["delete_files", "delete_user_files"]
