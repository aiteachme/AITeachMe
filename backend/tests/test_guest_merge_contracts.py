from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    ChatMessage,
    ChatSession,
    Course,
    CourseFileLink,
    CourseShare,
    CourseShareImport,
    Highlight,
    LearningLogRecord,
    MemoryRecord,
    RawFile,
    RetrievalChunk,
    User,
    UserMergeJob,
)
from app.shared.infra.storage.course_scope import build_user_file_storage_scope
from app.workflows.support.auth import merge


class _MemoryStore:
    def __init__(self, files: dict[str, bytes], *, fail_writes: bool = False) -> None:
        self.files = dict(files)
        self.fail_writes = fail_writes

    @staticmethod
    def user_file_scope(*, user_id: str):
        return build_user_file_storage_scope(user_id=user_id)

    async def exists(self, key: str) -> bool:
        return key in self.files

    async def read_bytes(self, key: str) -> bytes:
        return self.files[key]

    async def write_bytes(self, key: str, data: bytes) -> None:
        if self.fail_writes:
            raise OSError("object storage write failed")
        self.files[key] = data

    async def list_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self.files if key.startswith(prefix))

    async def delete_prefix(self, prefix: str) -> int:
        keys = [key for key in self.files if key.startswith(prefix)]
        for key in keys:
            self.files.pop(key, None)
        return len(keys)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Course.__table__,
            RawFile.__table__,
            CourseFileLink.__table__,
            CourseShare.__table__,
            CourseShareImport.__table__,
            Highlight.__table__,
            ChatSession.__table__,
            ChatMessage.__table__,
            MemoryRecord.__table__,
            LearningLogRecord.__table__,
            RetrievalChunk.__table__,
            UserMergeJob.__table__,
        ],
    )
    return engine


def _raw_file(file_id: str, *, user_id: str, content_hash: str, file_path: str) -> RawFile:
    return RawFile(
        id=file_id,
        user_id=user_id,
        filename=f"{file_id}.pdf",
        filetype="pdf",
        file_path=file_path,
        markdown_path=f"{file_path}.md",
        asset_dir=f"{file_path}.assets",
        content_hash=content_hash,
        file_size_bytes=4,
        parse_request_signature="default",
        status="completed",
    )


def test_unbound_files_are_copied_deduplicated_and_remapped_in_global_chats(
    monkeypatch,
) -> None:
    unique = _raw_file(
        "source-unique",
        user_id="guest",
        content_hash="unique-hash",
        file_path="users/guest/files/unique/raw.pdf",
    )
    duplicate = _raw_file(
        "source-duplicate",
        user_id="guest",
        content_hash="same-hash",
        file_path="users/guest/files/duplicate/raw.pdf",
    )
    target_file = _raw_file(
        "target-existing",
        user_id="target",
        content_hash="same-hash",
        file_path="users/target/files/existing/raw.pdf",
    )
    store = _MemoryStore(
        {
            unique.file_path: b"raw!",
            unique.markdown_path: b"markdown",
            f"{unique.asset_dir}/page.png": b"image",
        }
    )
    monkeypatch.setattr(merge, "get_content_store", lambda: store)

    with Session(_engine(), expire_on_commit=False) as session:
        session.add_all(
            [
                User(id="guest", username="guest"),
                User(id="target", username="target", is_registered=True),
                unique,
                duplicate,
                target_file,
                Highlight(user_id="guest", file_id=duplicate.id, selected_text="重点"),
                ChatSession(
                    id="guest-chat",
                    course_id="",
                    user_id="guest",
                    title="全局对话",
                    library_file_id=duplicate.id,
                ),
            ]
        )
        session.commit()
        session.add(
            ChatMessage(
                course_id="",
                user_id="guest",
                session_id="guest-chat",
                turn_id="turn-1",
                role="user",
                content="解释这个文件",
            )
        )
        session.commit()

        mapping, copied_prefixes = merge._clone_unbound_files(
            session,
            source_user_id="guest",
            target_user_id="target",
        )
        merge._clone_global_chats(
            session,
            source_user_id="guest",
            target_user_id="target",
            file_mapping=mapping,
            merge_job_id="merge-1",
        )
        session.commit()

        assert mapping[duplicate.id] == target_file.id
        cloned = session.get(RawFile, mapping[unique.id])
        assert cloned is not None and cloned.user_id == "target"
        assert session.get(RawFile, unique.id).user_id == "guest"
        assert copied_prefixes == [store.user_file_scope(user_id="target").file_prefix(
            file_id=cloned.id,
            filename=unique.filename,
        )]
        assert store.files[cloned.file_path] == b"raw!"
        assert store.files[f"{cloned.asset_dir}/page.png"] == b"image"

        target_chat = session.exec(
            select(ChatSession).where(ChatSession.user_id == "target")
        ).one()
        assert target_chat.library_file_id == target_file.id
        assert target_chat.meta_json["guest_merge_source_session_id"] == "guest-chat"
        target_message = session.exec(
            select(ChatMessage).where(ChatMessage.user_id == "target")
        ).one()
        assert target_message.content == "解释这个文件"
        assert target_message.source_chunk_id is None
        assert session.exec(
            select(Highlight).where(
                Highlight.user_id == "target",
                Highlight.file_id == target_file.id,
            )
        ).one().selected_text == "重点"


def test_unbound_file_storage_failure_rolls_back_target_rows(monkeypatch) -> None:
    source = _raw_file(
        "source-failure",
        user_id="guest",
        content_hash="failure-hash",
        file_path="users/guest/files/failure/raw.pdf",
    )
    store = _MemoryStore({source.file_path: b"raw!"}, fail_writes=True)
    monkeypatch.setattr(merge, "get_content_store", lambda: store)

    with Session(_engine(), expire_on_commit=False) as session:
        session.add_all(
            [
                User(id="guest", username="guest"),
                User(id="target", username="target", is_registered=True),
                source,
            ]
        )
        session.commit()

        try:
            merge._clone_unbound_files(
                session,
                source_user_id="guest",
                target_user_id="target",
            )
        except OSError as exc:
            assert "object storage write failed" in str(exc)
        else:  # pragma: no cover - contract assertion
            raise AssertionError("Expected the storage copy to fail")

        assert session.exec(select(RawFile).where(RawFile.user_id == "target")).all() == []
        assert not any(key.startswith("users/target/files/") for key in store.files)


def test_learning_logs_are_remapped_to_imported_course_ids() -> None:
    with Session(_engine(), expire_on_commit=False) as session:
        session.add_all(
            [
                User(id="guest", username="guest"),
                User(id="target", username="target", is_registered=True),
                LearningLogRecord(
                    user_id="guest",
                    event_type="exam",
                    course_id="course-source",
                    summary="完成诊断卷",
                ),
                LearningLogRecord(
                    user_id="guest",
                    event_type="chat",
                    course_id="",
                    summary="全局学习记录",
                ),
            ]
        )
        session.commit()

        merge._copy_memory(
            session,
            source_user_id="guest",
            target_user_id="target",
            course_mapping={"course-source": "course-imported"},
        )
        session.commit()

        target_logs = session.exec(
            select(LearningLogRecord)
            .where(LearningLogRecord.user_id == "target")
            .order_by(LearningLogRecord.id)
        ).all()
        assert [item.course_id for item in target_logs] == ["course-imported", ""]


def _merge_job_fixture(session: Session) -> UserMergeJob:
    source = User(id="guest", username="guest")
    target = User(id="target", username="target", email="target@example.com", is_registered=True)
    source_course = Course(
        id="course-source",
        user_id=source.id,
        slug="source",
        name="Source Course",
    )
    job = UserMergeJob(
        id="merge-job",
        source_user_id=source.id,
        target_user_id=target.id,
    )
    session.add_all([source, target, source_course, job])
    session.commit()
    return job


def _patch_course_merge_dependencies(monkeypatch, session: Session, *, fail_after_import: bool = False) -> None:
    monkeypatch.setattr(merge, "export_course", lambda *_args, **_kwargs: Path("missing-package.atmx"))

    def fake_import(_session, *, user_id, commit, **_kwargs):
        assert user_id == "target"
        assert commit is False
        _session.add(
            Course(
                id="course-imported",
                user_id=user_id,
                slug="imported",
                name="Imported Course",
            )
        )
        _session.flush()
        return SimpleNamespace(course_id="course-imported")

    monkeypatch.setattr(merge, "import_course", fake_import)
    monkeypatch.setattr(merge, "_deduplicate_staged_files", lambda *_args, **_kwargs: [])
    if fail_after_import:
        monkeypatch.setattr(
            merge,
            "_clone_unbound_files",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")),
        )
    else:
        monkeypatch.setattr(merge, "_clone_unbound_files", lambda *_args, **_kwargs: ({}, []))
    monkeypatch.setattr(merge, "_clone_global_chats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(merge, "_copy_memory", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(merge, "refresh_course_profile_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(merge, "refresh_user_profile_summary", lambda *_args, **_kwargs: None)


def test_course_merge_imports_into_target_in_one_transaction(monkeypatch) -> None:
    store = _MemoryStore({})
    monkeypatch.setattr(merge, "get_content_store", lambda: store)
    with Session(_engine(), expire_on_commit=False) as session:
        job = _merge_job_fixture(session)
        _patch_course_merge_dependencies(monkeypatch, session)

        completed = merge.run_guest_merge(session, job_id=job.id, target_user_id="target")

        assert completed.status == "completed"
        assert session.get(Course, "course-imported").user_id == "target"
        assert session.get(Course, "course-imported").status == "active"
        assert session.get(Course, "course-source").user_id == "guest"
        assert session.get(User, "guest").merged_into_user_id == "target"


def test_course_merge_failure_rolls_back_target_staging_rows(monkeypatch) -> None:
    store = _MemoryStore({})
    monkeypatch.setattr(merge, "get_content_store", lambda: store)
    monkeypatch.setattr(merge, "cleanup_imported_course_artifacts", lambda *_args, **_kwargs: None)
    with Session(_engine(), expire_on_commit=False) as session:
        job = _merge_job_fixture(session)
        _patch_course_merge_dependencies(monkeypatch, session, fail_after_import=True)

        try:
            merge.run_guest_merge(session, job_id=job.id, target_user_id="target")
        except OSError as exc:
            assert str(exc) == "copy failed"
        else:  # pragma: no cover - contract assertion
            raise AssertionError("Expected merge failure")

        assert session.get(Course, "course-imported") is None
        assert session.get(Course, "course-source").user_id == "guest"
        assert session.get(User, "guest").merged_into_user_id is None
        assert session.get(UserMergeJob, job.id).status == "failed"


def test_expired_merge_cleanup_removes_guest_source_assets(monkeypatch) -> None:
    store = _MemoryStore(
        {
            "users/guest/files/source/raw.pdf": b"raw",
            "users/guest/courses/course_aaaaaaaaaaaa/knowledge.md": b"course",
            "users/target/files/keep/raw.pdf": b"keep",
        }
    )
    monkeypatch.setattr(merge, "get_content_store", lambda: store)
    learner_docs_deleted: list[str] = []
    monkeypatch.setattr(
        merge,
        "_delete_guest_learner_doc",
        lambda *, source_user_id: learner_docs_deleted.append(source_user_id),
    )

    def delete_course(session, *, course, **_kwargs):
        session.delete(course)
        session.commit()
        return {"course": 1}

    monkeypatch.setattr(merge, "delete_course_with_all_content", delete_course)

    with Session(_engine(), expire_on_commit=False) as session:
        source = User(
            id="guest",
            username="guest",
            merged_into_user_id="target",
        )
        target = User(id="target", username="target", is_registered=True)
        job = UserMergeJob(
            id="expired-merge",
            source_user_id=source.id,
            target_user_id=target.id,
            status="completed",
            course_mapping_json={"course_aaaaaaaaaaaa": "course_bbbbbbbbbbbb"},
            progress_json={"imported_course_ids": ["course_bbbbbbbbbbbb"]},
            recovery_expires_at=merge.utcnow() - timedelta(seconds=1),
        )
        session.add_all(
            [
                source,
                target,
                Course(
                    id="course_aaaaaaaaaaaa",
                    user_id=source.id,
                    slug="source",
                    name="Source Course",
                ),
                _raw_file(
                    "source-file",
                    user_id=source.id,
                    content_hash="source-hash",
                    file_path="users/guest/files/source/raw.pdf",
                ),
                ChatSession(
                    id="source-chat",
                    course_id="",
                    user_id=source.id,
                    title="Source chat",
                ),
                MemoryRecord(
                    key="source-memory",
                    user_id=source.id,
                    content="source memory",
                ),
                LearningLogRecord(
                    user_id=source.id,
                    event_type="chat",
                    course_id="",
                    summary="source log",
                ),
                job,
            ]
        )
        session.commit()
        session.add(
            ChatMessage(
                course_id="",
                user_id=source.id,
                session_id="source-chat",
                turn_id="source-turn",
                role="user",
                content="source message",
            )
        )
        session.commit()

        assert merge.cleanup_expired_guest_merge(session, job_id=job.id) is True
        assert merge.cleanup_expired_guest_merge(session, job_id=job.id) is False
        assert session.exec(select(Course).where(Course.user_id == source.id)).all() == []
        assert session.exec(select(RawFile).where(RawFile.user_id == source.id)).all() == []
        assert session.exec(select(ChatSession).where(ChatSession.user_id == source.id)).all() == []
        assert session.exec(select(MemoryRecord).where(MemoryRecord.user_id == source.id)).all() == []
        completed = session.get(UserMergeJob, job.id)
        assert completed.recovery_expires_at is None
        assert completed.progress_json["source_cleanup_status"] == "completed"
        assert learner_docs_deleted == [source.id]
        assert not any(key.startswith("users/guest/") for key in store.files)
        assert store.files["users/target/files/keep/raw.pdf"] == b"keep"


def test_expired_merge_cleanup_failure_is_retryable(monkeypatch) -> None:
    store = _MemoryStore({"users/guest/files/source/raw.pdf": b"raw"})
    original_delete_prefix = store.delete_prefix
    delete_attempts = 0

    async def fail_first_delete(prefix: str) -> int:
        nonlocal delete_attempts
        delete_attempts += 1
        if delete_attempts == 1:
            raise OSError("storage unavailable")
        return await original_delete_prefix(prefix)

    monkeypatch.setattr(store, "delete_prefix", fail_first_delete)
    monkeypatch.setattr(merge, "get_content_store", lambda: store)
    monkeypatch.setattr(merge, "_delete_guest_learner_doc", lambda **_kwargs: None)

    with Session(_engine(), expire_on_commit=False) as session:
        source = User(id="guest", username="guest", merged_into_user_id="target")
        target = User(id="target", username="target", is_registered=True)
        job = UserMergeJob(
            id="retryable-merge",
            source_user_id=source.id,
            target_user_id=target.id,
            status="completed",
            recovery_expires_at=merge.utcnow() - timedelta(seconds=1),
        )
        session.add_all([source, target, job])
        session.commit()

        try:
            merge.cleanup_expired_guest_merge(session, job_id=job.id)
        except OSError as exc:
            assert str(exc) == "storage unavailable"
        else:  # pragma: no cover - contract assertion
            raise AssertionError("Expected guest cleanup storage failure")

        failed = session.get(UserMergeJob, job.id)
        assert failed.progress_json["source_cleanup_status"] == "failed"
        assert failed.recovery_expires_at > merge.utcnow()

        failed.recovery_expires_at = merge.utcnow() - timedelta(seconds=1)
        session.add(failed)
        session.commit()
        assert merge.cleanup_expired_guest_merge(session, job_id=job.id) is True
        assert not any(key.startswith("users/guest/") for key in store.files)
