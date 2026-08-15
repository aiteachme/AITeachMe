"""Explicit, durable guest-data merge built on the existing .atmx pipeline."""

from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import Session, select

from app.models import (
    ChatMessage,
    ChatSession,
    Course,
    CourseFileLink,
    ExamPaper,
    Highlight,
    LearningLogRecord,
    MemoryRecord,
    RawFile,
    User,
    UserKnowledgeState,
    UserMergeJob,
)
from app.schemas.export_import import ExportOptions, ImportOptions
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.storage import get_content_store, run_store_sync
from app.utils.course import GLOBAL_COURSE_ALIASES
from app.utils.time import utcnow
from app.workflows.profile.common.lib.course_profile import refresh_course_profile_summary
from app.workflows.profile.common.lib.user_profile import refresh_user_profile_summary
from app.workflows.support.export_import import (
    cleanup_imported_course_artifacts,
    export_course,
    import_course,
)

def guest_asset_counts(session: Session, *, user_id: str) -> dict[str, int]:
    def count(model) -> int:
        return int(session.exec(
            select(sa.func.count()).select_from(model).where(model.user_id == user_id)
        ).one())

    courses = count(Course)
    files = count(RawFile)
    chats = count(ChatSession)
    exams = count(ExamPaper)
    profile = count(UserKnowledgeState)
    memory = count(MemoryRecord) + count(LearningLogRecord)
    return {
        "courses": courses,
        "files": files,
        "chats": chats,
        "exams": exams,
        "profile_records": profile,
        "memory_records": memory,
        "total": courses + files + chats + exams + profile + memory,
    }


def create_merge_offer(
    session: Session,
    *,
    source_user_id: str,
    target_user_id: str,
) -> dict | None:
    if source_user_id == target_user_id:
        return None
    source = session.get(User, source_user_id)
    target = session.get(User, target_user_id)
    if (
        source is None
        or source.is_registered
        or source.merged_into_user_id is not None
        or target is None
        or not target.is_registered
    ):
        return None
    counts = guest_asset_counts(session, user_id=source.id)
    if counts["total"] <= 0:
        return None
    job = session.exec(
        select(UserMergeJob).where(
            UserMergeJob.source_user_id == source.id,
            UserMergeJob.target_user_id == target.id,
        )
    ).first()
    if job is None:
        job = UserMergeJob(
            id=f"umj_{uuid4().hex}",
            source_user_id=source.id,
            target_user_id=target.id,
            status="pending",
            asset_counts_json=counts,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
    elif job.status not in {"completed", "running"}:
        job.asset_counts_json = counts
        job.status = "pending"
        job.updated_at = utcnow()
    session.add(job)
    session.commit()
    return {"job_id": job.id, "counts": counts, "status": job.status}


def _deduplicate_staged_files(
    session: Session,
    *,
    imported_course_ids: list[str],
    target_user_id: str,
) -> list[str]:
    if not imported_course_ids:
        return []
    imported_course_id_set = set(imported_course_ids)
    staged_files = session.exec(
        select(RawFile).where(
            RawFile.user_id == target_user_id,
            RawFile.origin_course_id.in_(tuple(imported_course_ids)),
        )
    ).all()
    existing_files = session.exec(
        select(RawFile).where(
            RawFile.user_id == target_user_id,
            RawFile.status != "failed",
        )
    ).all()
    deduplicated_prefixes: list[str] = []
    file_scope = get_content_store().user_file_scope(user_id=target_user_id)
    for staged in staged_files:
        if staged.content_hash is None or staged.file_size_bytes is None:
            continue
        existing = next(
            (
                candidate
                for candidate in existing_files
                if candidate.id != staged.id
                and candidate.origin_course_id not in imported_course_id_set
                and candidate.content_hash == staged.content_hash
                and candidate.file_size_bytes == staged.file_size_bytes
                and candidate.filetype == staged.filetype
                and candidate.parse_request_signature == staged.parse_request_signature
            ),
            None,
        )
        if existing is None:
            continue
        from app.models import RetrievalChunk

        session.exec(sa.update(CourseFileLink).where(CourseFileLink.file_id == staged.id).values(file_id=existing.id))
        session.exec(sa.update(RetrievalChunk).where(RetrievalChunk.file_id == staged.id).values(file_id=existing.id))
        session.exec(sa.update(Highlight).where(Highlight.file_id == staged.id).values(file_id=existing.id))
        session.exec(sa.update(ChatSession).where(ChatSession.library_file_id == staged.id).values(library_file_id=existing.id))
        deduplicated_prefixes.append(
            file_scope.file_prefix(file_id=staged.id, filename=staged.filename)
        )
        session.delete(staged)
    session.flush()
    return deduplicated_prefixes


def _copy_memory(session: Session, *, source_user_id: str, target_user_id: str) -> None:
    for record in session.exec(select(MemoryRecord).where(MemoryRecord.user_id == source_user_id)).all():
        target_key = f"{target_user_id}:{record.key}"
        if session.exec(select(MemoryRecord).where(MemoryRecord.key == target_key)).first() is None:
            session.add(
                MemoryRecord(
                    key=target_key,
                    user_id=target_user_id,
                    content=record.content,
                    tag=record.tag,
                    importance=record.importance,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
    existing_log_keys = {
        (item.event_type, item.course_id, item.summary, item.created_at)
        for item in session.exec(
            select(LearningLogRecord).where(LearningLogRecord.user_id == target_user_id)
        ).all()
    }
    for record in session.exec(
        select(LearningLogRecord).where(LearningLogRecord.user_id == source_user_id)
    ).all():
        key = (record.event_type, record.course_id, record.summary, record.created_at)
        if key not in existing_log_keys:
            session.add(
                LearningLogRecord(
                    user_id=target_user_id,
                    event_type=record.event_type,
                    course_id=record.course_id,
                    summary=record.summary,
                    metadata_json=dict(record.metadata_json or {}),
                    created_at=record.created_at,
                )
            )


def _matching_target_file(session: Session, *, source: RawFile, target_user_id: str) -> RawFile | None:
    if (
        source.status == "failed"
        or not source.content_hash
        or source.file_size_bytes is None
    ):
        return None
    return session.exec(
        select(RawFile).where(
            RawFile.user_id == target_user_id,
            RawFile.content_hash == source.content_hash,
            RawFile.file_size_bytes == source.file_size_bytes,
            RawFile.filetype == source.filetype,
            RawFile.parse_request_signature == source.parse_request_signature,
            RawFile.status != "failed",
        )
    ).first()


def _copy_storage_object(*, source_key: str, target_key: str, required: bool) -> bool:
    store = get_content_store()
    if not run_store_sync(store.exists, source_key, default=False):
        if required:
            raise FileNotFoundError(f"Guest merge source object is missing: {source_key}")
        return False
    payload = run_store_sync(store.read_bytes, source_key)
    if payload is None:
        raise OSError(f"Guest merge could not read source object: {source_key}")
    run_store_sync(store.write_bytes, target_key, payload)
    return True


def _clone_unbound_files(
    session: Session,
    *,
    source_user_id: str,
    target_user_id: str,
) -> tuple[dict[str, str], list[str]]:
    """Clone global library files without changing the recoverable guest source."""

    linked_file_ids = set(
        session.exec(
            select(CourseFileLink.file_id).where(CourseFileLink.user_id == source_user_id)
        ).all()
    )
    source_files = session.exec(
        select(RawFile).where(
            RawFile.user_id == source_user_id,
            RawFile.origin_course_id.is_(None),
        )
    ).all()
    source_files = [item for item in source_files if item.id not in linked_file_ids]
    file_mapping: dict[str, str] = {}
    copied_prefixes: list[str] = []
    store = get_content_store()

    try:
        for source in source_files:
            existing = _matching_target_file(session, source=source, target_user_id=target_user_id)
            if existing is not None:
                file_mapping[source.id] = existing.id
                continue

            new_id = f"file_{uuid4().hex}"
            target_scope = store.user_file_scope(user_id=target_user_id)
            target_prefix = target_scope.file_prefix(file_id=new_id, filename=source.filename)
            copied_prefixes.append(target_prefix)
            target_file_key = target_scope.raw_file_key(
                file_id=new_id,
                filename=source.filename,
                extension=source.filetype,
            )
            target_markdown_key = target_scope.raw_markdown_key(file_id=new_id, filename=source.filename)
            target_asset_prefix = target_scope.asset_prefix(file_id=new_id, filename=source.filename)

            if source.file_path:
                _copy_storage_object(
                    source_key=source.file_path,
                    target_key=target_file_key,
                    required=True,
                )
            if source.markdown_path:
                _copy_storage_object(
                    source_key=source.markdown_path,
                    target_key=target_markdown_key,
                    required=False,
                )
            if source.asset_dir:
                source_asset_prefix = source.asset_dir.rstrip("/") + "/"
                for source_key in run_store_sync(store.list_prefix, source_asset_prefix, default=[]):
                    relative_key = source_key[len(source_asset_prefix):]
                    if relative_key:
                        _copy_storage_object(
                            source_key=source_key,
                            target_key=f"{target_asset_prefix}{relative_key}",
                            required=True,
                        )

            values = source.model_dump()
            values.update(
                id=new_id,
                user_id=target_user_id,
                origin_course_id=None,
                origin_course_name=None,
                file_path=target_file_key if source.file_path else "",
                markdown_path=target_markdown_key if source.markdown_path else None,
                asset_dir=target_asset_prefix.rstrip("/") if source.asset_dir else None,
                storage_uri=None,
                markdown_uri=None,
            )
            session.add(RawFile(**values))
            file_mapping[source.id] = new_id
        session.flush()

        target_highlight_keys = {
            (item.file_id, item.selected_text, item.anchor_id, item.color, item.description)
            for item in session.exec(select(Highlight).where(Highlight.user_id == target_user_id)).all()
        }
        for source_highlight in session.exec(
            select(Highlight).where(Highlight.user_id == source_user_id)
        ).all():
            target_file_id = file_mapping.get(source_highlight.file_id)
            if target_file_id is None:
                continue
            signature = (
                target_file_id,
                source_highlight.selected_text,
                source_highlight.anchor_id,
                source_highlight.color,
                source_highlight.description,
            )
            if signature in target_highlight_keys:
                continue
            values = source_highlight.model_dump()
            values.update(id=None, user_id=target_user_id, file_id=target_file_id)
            session.add(Highlight(**values))
            target_highlight_keys.add(signature)
        session.flush()
        return file_mapping, copied_prefixes
    except Exception:
        session.rollback()
        for prefix in copied_prefixes:
            run_store_sync(store.delete_prefix, prefix, default=0)
        raise


def _clone_global_chats(
    session: Session,
    *,
    source_user_id: str,
    target_user_id: str,
    file_mapping: dict[str, str],
    merge_job_id: str,
) -> None:
    target_sessions = session.exec(
        select(ChatSession).where(
            ChatSession.user_id == target_user_id,
            ChatSession.course_id.in_(tuple(GLOBAL_COURSE_ALIASES)),
        )
    ).all()
    existing_sources = {
        str((item.meta_json or {}).get("guest_merge_source_session_id")): item.id
        for item in target_sessions
        if isinstance(item.meta_json, dict) and (item.meta_json or {}).get("guest_merge_source_session_id")
    }
    source_sessions = session.exec(
        select(ChatSession).where(
            ChatSession.user_id == source_user_id,
            ChatSession.course_id.in_(tuple(GLOBAL_COURSE_ALIASES)),
        )
    ).all()
    for source_chat in source_sessions:
        if source_chat.id in existing_sources:
            continue
        new_session_id = f"chat_{uuid4().hex}"
        metadata = dict(source_chat.meta_json or {}) if isinstance(source_chat.meta_json, dict) else {}
        metadata.update(
            guest_merge_job_id=merge_job_id,
            guest_merge_source_session_id=source_chat.id,
        )
        values = source_chat.model_dump()
        values.update(
            id=new_session_id,
            user_id=target_user_id,
            course_id="",
            library_file_id=file_mapping.get(source_chat.library_file_id or ""),
            meta_json=metadata,
        )
        session.add(ChatSession(**values))
        session.flush()

        messages = session.exec(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == source_user_id,
                ChatMessage.session_id == source_chat.id,
            )
            .order_by(ChatMessage.id)
        ).all()
        for message in messages:
            message_values = message.model_dump()
            message_values.update(
                id=None,
                user_id=target_user_id,
                course_id="",
                session_id=new_session_id,
                source_chunk_id=None,
            )
            session.add(ChatMessage(**message_values))
    session.flush()


def run_guest_merge(session: Session, *, job_id: str, target_user_id: str) -> UserMergeJob:
    job = session.exec(
        select(UserMergeJob).where(UserMergeJob.id == job_id).with_for_update()
    ).first()
    if job is None or job.target_user_id != target_user_id:
        raise AITeachMeError(detail="迁移任务不存在。", status_code=404, error_code="USER_MERGE_NOT_FOUND")
    if job.status == "completed":
        return job
    if job.status == "running":
        updated_at = job.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if updated_at > utcnow() - timedelta(hours=1):
            raise AITeachMeError(detail="迁移任务正在执行。", status_code=409, error_code="USER_MERGE_RUNNING")
        job.status = "failed"
        job.failure_reason = "迁移任务运行超时，已转入安全重试。"
        job.retry_count += 1
        job.updated_at = utcnow()
        session.add(job)

    source = session.get(User, job.source_user_id)
    target = session.get(User, job.target_user_id)
    if source is None or target is None or source.is_registered or not target.is_registered:
        raise AITeachMeError(detail="迁移账号状态无效。", status_code=409, error_code="USER_MERGE_INVALID")

    job.status = "running"
    job.progress_json = {"imported_course_ids": []}
    job.failure_reason = None
    job.updated_at = utcnow()
    session.add(job)
    session.commit()

    imported_ids: list[str] = []
    imported_file_prefixes: list[str] = []
    deduplicated_file_prefixes: list[str] = []
    course_mapping: dict[str, str] = {}
    copied_file_prefixes: list[str] = []
    try:
        source_courses = session.exec(select(Course).where(Course.user_id == source.id)).all()
        for source_course in source_courses:
            package_path = export_course(
                session,
                course_id=source_course.id,
                options=ExportOptions(
                    include_raw_markdowns=True,
                    include_knowledge_docs=True,
                    include_chat_history=True,
                    include_exam_history=True,
                    include_profile=True,
                ),
            )
            try:
                result = import_course(
                    session,
                    file_path=Path(package_path),
                    options=ImportOptions(new_course_name=source_course.name, rebuild_embeddings=False),
                    user_id=target.id,
                    commit=False,
                )
            finally:
                Path(package_path).unlink(missing_ok=True)
            imported_ids.append(result.course_id)
            course_mapping[source_course.id] = result.course_id
            imported = session.get(Course, result.course_id)
            if imported is not None:
                imported.status = "staging"
                session.add(imported)
                session.flush()
            file_scope = get_content_store().user_file_scope(user_id=target.id)
            for imported_file in session.exec(
                select(RawFile).where(
                    RawFile.user_id == target.id,
                    RawFile.origin_course_id == result.course_id,
                )
            ).all():
                imported_file_prefixes.append(
                    file_scope.file_prefix(
                        file_id=imported_file.id,
                        filename=imported_file.filename,
                    )
                )

        deduplicated_file_prefixes = _deduplicate_staged_files(
            session,
            imported_course_ids=imported_ids,
            target_user_id=target.id,
        )
        session.exec(
            sa.update(Course).where(Course.id.in_(imported_ids)).values(status="active")
        )
        file_mapping, copied_file_prefixes = _clone_unbound_files(
            session,
            source_user_id=source.id,
            target_user_id=target.id,
        )
        _clone_global_chats(
            session,
            source_user_id=source.id,
            target_user_id=target.id,
            file_mapping=file_mapping,
            merge_job_id=job.id,
        )
        _copy_memory(session, source_user_id=source.id, target_user_id=target.id)
        for course_id in imported_ids:
            refresh_course_profile_summary(session, course_id=course_id, auto_commit=False)
        refresh_user_profile_summary(session, user_id=target.id, auto_commit=False)
        source.merged_into_user_id = target.id
        source.updated_at = utcnow()
        job.status = "completed"
        job.course_mapping_json = course_mapping
        job.progress_json = {"imported_course_ids": imported_ids}
        job.recovery_expires_at = utcnow() + timedelta(days=7)
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        session.add(source)
        session.add(job)
        session.commit()
        store = get_content_store()
        for prefix in deduplicated_file_prefixes:
            run_store_sync(store.delete_prefix, prefix, default=0)
        session.refresh(job)
        return job
    except Exception as exc:
        session.rollback()
        store = get_content_store()
        for prefix in copied_file_prefixes:
            run_store_sync(store.delete_prefix, prefix, default=0)
        for prefix in imported_file_prefixes:
            run_store_sync(store.delete_prefix, prefix, default=0)
        for course_id in imported_ids:
            try:
                cleanup_imported_course_artifacts(course_id, user_id=target.id)
            except Exception:
                pass
        job = session.get(UserMergeJob, job_id)
        if job is not None:
            job.status = "failed"
            job.retry_count += 1
            job.failure_reason = str(exc)[:2000]
            job.progress_json = {"imported_course_ids": []}
            job.updated_at = utcnow()
            session.add(job)
            session.commit()
        raise
