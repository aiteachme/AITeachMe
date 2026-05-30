from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import RawFile, Course, CourseFileLink, IngestStatus, TaskStatus, User
from app.repositories.files_repo import list_raw_files_by_user
from app.shared.infra.exceptions import FileCountLimitError, FileTooLargeError, UnsupportedFileTypeError
from app.shared.infra.storage.course_scope import build_user_file_storage_scope
from app.workflows.ingest.intake import catalog, uploads
from app.workflows.ingest.intake.parse_dispatch import ready_file_ids_for_course_indexing


class _FakeContentStore:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []
        self.texts: dict[str, str] = {}

    @staticmethod
    def user_file_scope(*, user_id: str):
        return build_user_file_storage_scope(user_id=user_id)

    async def write_file(self, key: str, local_path: Path) -> None:
        self.writes.append((key, local_path.read_bytes()))

    async def read_text(self, key: str, *, default: str | None = None) -> str | None:
        return self.texts.get(key, default)

    async def list_prefix(self, prefix: str) -> list[str]:
        return []


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(BytesIO(content), filename=filename)


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Course.__table__, RawFile.__table__, CourseFileLink.__table__],
    )
    return Session(engine, expire_on_commit=False)


def _install_fake_store(monkeypatch) -> _FakeContentStore:
    fake_store = _FakeContentStore()
    monkeypatch.setattr(uploads, "get_content_store", lambda: fake_store)
    monkeypatch.setattr(catalog, "get_content_store", lambda: fake_store)
    return fake_store


def test_duplicate_user_upload_reuses_existing_file(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        first_data, first_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
            )
        )
        second_data, second_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("renamed.pdf", b"same pdf bytes")],
            )
        )

        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 1
    assert len(raw_files) == 1
    assert len(fake_store.writes) == 1
    assert first_parse_ids == [raw_files[0].id]
    assert second_parse_ids == []
    assert first_data.started_parse_count == 1
    assert second_data.started_parse_count == 0
    assert second_data.uploaded_items[0].id == first_data.uploaded_items[0].id
    assert raw_files[0].parse_request_signature == "default"


def test_upload_batch_rejects_more_than_max_files(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        with pytest.raises(FileCountLimitError):
            asyncio.run(
                uploads.save_uploaded_files_and_request_parse(
                    session,
                    owner_user_id="user_a",
                    files=[_upload(f"notes-{index}.txt", b"small") for index in range(11)],
                )
            )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 0
    assert raw_files == []
    assert fake_store.writes == []


def test_upload_batch_rejects_total_size_over_limit(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        with pytest.raises(FileTooLargeError):
            asyncio.run(
                uploads.save_uploaded_files_and_request_parse(
                    session,
                    owner_user_id="user_a",
                    files=[
                        _upload("part-a.txt", b"a" * (6 * 1024 * 1024)),
                        _upload("part-b.txt", b"b" * (5 * 1024 * 1024)),
                    ],
                )
            )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 0
    assert raw_files == []
    assert fake_store.writes == []


def test_upload_accepts_pptx_but_rejects_ppt(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        data, parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("slides.pptx", b"fake pptx bytes")],
            )
        )
        with pytest.raises(UnsupportedFileTypeError):
            asyncio.run(
                uploads.save_uploaded_files_and_request_parse(
                    session,
                    owner_user_id="user_a",
                    files=[_upload("legacy.ppt", b"fake ppt bytes")],
                )
            )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 1
    assert len(raw_files) == 1
    assert raw_files[0].filetype == "pptx"
    assert data.started_parse_count == 1
    assert parse_ids == [raw_files[0].id]
    assert len(fake_store.writes) == 1


def test_storage_only_markdown_marks_file_ready(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    fake_store.texts["users/user_a/files/file_ready/markdown.md"] = "# 已解析内容"

    raw_file = RawFile(
        id="file_ready",
        user_id="user_a",
        filename="notes.pdf",
        filetype="pdf",
        file_path="users/user_a/files/file_ready/source.pdf",
        markdown_path="users/user_a/files/file_ready/markdown.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
    )

    record = catalog.build_file_record(raw_file)

    assert record.markdown_ready is True
    assert record.markdown_content == "# 已解析内容"


def test_ready_file_ids_for_course_indexing_includes_completed_markdown_path() -> None:
    ready_file = RawFile(
        id="file_ready",
        user_id="user_a",
        filename="ready.pdf",
        filetype="pdf",
        file_path="raw/ready.pdf",
        markdown_path="parsed/ready.md",
        status=TaskStatus.COMPLETED.value,
        ingest_status=IngestStatus.READY_FOR_DIGEST.value,
    )
    pending_file = RawFile(
        id="file_pending",
        user_id="user_a",
        filename="pending.pdf",
        filetype="pdf",
        file_path="raw/pending.pdf",
        markdown_path="parsed/pending.md",
        status=TaskStatus.PENDING.value,
        ingest_status=IngestStatus.PENDING.value,
    )

    assert ready_file_ids_for_course_indexing([ready_file, pending_file, ready_file]) == ["file_ready"]


def test_duplicate_course_upload_links_once_and_starts_parse_once(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        session.add(User(id="user_a", username="user_a"))
        session.add(Course(user_id="user_a", id="course_math00000000", name="Math"))
        session.commit()

        data, parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                course_id="course_math00000000",
                owner_user_id="user_a",
                files=[
                    _upload("chapter.pdf", b"same pdf bytes"),
                    _upload("chapter-copy.pdf", b"same pdf bytes"),
                ],
            )
        )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)
        links = list(session.exec(select(CourseFileLink)).all())

    assert total == 1
    assert len(raw_files) == 1
    assert len(links) == 1
    assert len(fake_store.writes) == 1
    assert parse_ids == [raw_files[0].id]
    assert data.started_parse_count == 1
    assert len(data.uploaded_items) == 2
    assert data.uploaded_items[0].id == data.uploaded_items[1].id


def test_duplicate_with_different_explicit_parser_creates_parse_variant(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        mineru_data, mineru_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
                parse_request_metadata={"requested_parser_provider": "mineru"},
            )
        )
        paddle_data, paddle_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
                parse_request_metadata={"requested_parser_provider": "paddle_ocr"},
            )
        )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 2
    assert len(raw_files) == 2
    assert len(fake_store.writes) == 2
    assert mineru_parse_ids != paddle_parse_ids
    assert mineru_data.uploaded_items[0].id != paddle_data.uploaded_items[0].id
    assert len({item.parse_request_signature for item in raw_files}) == 2


def test_duplicate_with_same_explicit_parser_reuses_signature(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    first_metadata = {
        "requested_parser_provider": "paddle_ocr",
        "paddle_ocr": {"api_token": "token-a"},
    }
    second_metadata = {
        "requested_parser_provider": "paddle-ocr",
        "paddle_ocr": {"api_token": "token-b"},
    }
    first_signature = uploads.build_parse_request_signature(first_metadata)
    second_signature = uploads.build_parse_request_signature(second_metadata)
    assert first_signature == second_signature
    assert uploads.build_parse_request_signature({"api_token": "token-a"}) == (
        uploads.build_parse_request_signature({"access_token": "token-b"})
    )
    assert "token-a" not in uploads.build_parse_request_signature(first_metadata)

    with _session() as session:
        first_data, first_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
                parse_request_metadata=first_metadata,
            )
        )
        second_data, second_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("renamed.pdf", b"same pdf bytes")],
                parse_request_metadata=second_metadata,
            )
        )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 1
    assert len(fake_store.writes) == 1
    assert first_parse_ids == [raw_files[0].id]
    assert second_parse_ids == []
    assert first_data.uploaded_items[0].id == second_data.uploaded_items[0].id
    assert raw_files[0].parse_request_signature.startswith("sha256:")


def test_default_upload_reuses_best_completed_parse_variant(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
                parse_request_metadata={"requested_parser_provider": "mineru"},
            )
        )
        mineru_file = session.exec(select(RawFile).where(RawFile.user_id == "user_a")).first()
        assert mineru_file is not None
        mineru_file.status = TaskStatus.COMPLETED.value
        mineru_file.parse_metadata_json = '{"parser_used":"mineru"}'
        session.add(mineru_file)
        session.commit()

        asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
                parse_request_metadata={"requested_parser_provider": "paddle_ocr"},
            )
        )
        paddle_file = session.exec(
            select(RawFile).where(RawFile.user_id == "user_a", RawFile.id != mineru_file.id)
        ).first()
        assert paddle_file is not None
        paddle_file.status = TaskStatus.COMPLETED.value
        paddle_file.parse_metadata_json = '{"parser_used":"paddle_ocr"}'
        session.add(paddle_file)
        session.commit()

        default_data, default_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("default.pdf", b"same pdf bytes")],
            )
        )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 2
    assert len(fake_store.writes) == 2
    assert default_parse_ids == []
    assert default_data.uploaded_items[0].id == paddle_file.id
    assert len(raw_files) == 2


def test_failed_duplicate_does_not_block_retry(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        first_data, first_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
            )
        )
        failed_file = session.get(RawFile, first_parse_ids[0])
        assert failed_file is not None
        failed_file.status = TaskStatus.FAILED.value
        session.add(failed_file)
        session.commit()

        second_data, second_parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                owner_user_id="user_a",
                files=[_upload("notes.pdf", b"same pdf bytes")],
            )
        )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)

    assert total == 2
    assert len(fake_store.writes) == 2
    assert first_parse_ids != second_parse_ids
    assert first_data.uploaded_items[0].id != second_data.uploaded_items[0].id
    assert len(raw_files) == 2
