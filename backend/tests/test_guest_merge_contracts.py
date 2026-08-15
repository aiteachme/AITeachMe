from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import ChatMessage, ChatSession, Course, CourseFileLink, Highlight, RawFile, User, UserMergeJob
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
            Highlight.__table__,
            ChatSession.__table__,
            ChatMessage.__table__,
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
