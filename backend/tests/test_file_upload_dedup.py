from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import RawFile, Subject, SubjectFileLink, User
from app.repositories.files_repo import list_raw_files_by_user
from app.shared.infra.storage.subject_scope import build_user_file_storage_scope
from app.workflows.ingest.intake import catalog, uploads


class _FakeContentStore:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes]] = []

    @staticmethod
    def user_file_scope(*, user_id: str):
        return build_user_file_storage_scope(user_id=user_id)

    async def write_file(self, key: str, local_path: Path) -> None:
        self.writes.append((key, local_path.read_bytes()))

    async def read_text(self, key: str, *, default: str | None = None) -> str | None:
        return default

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
        tables=[User.__table__, Subject.__table__, RawFile.__table__, SubjectFileLink.__table__],
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
    assert second_data.uploaded_items[0].uid == first_data.uploaded_items[0].uid


def test_duplicate_subject_upload_links_once_and_starts_parse_once(monkeypatch) -> None:
    fake_store = _install_fake_store(monkeypatch)
    with _session() as session:
        session.add(User(id="user_a", username="user_a"))
        session.add(Subject(user_id="user_a", slug="math", name="Math"))
        session.commit()

        data, parse_ids = asyncio.run(
            uploads.save_uploaded_files_and_request_parse(
                session,
                subject="math",
                owner_user_id="user_a",
                files=[
                    _upload("chapter.pdf", b"same pdf bytes"),
                    _upload("chapter-copy.pdf", b"same pdf bytes"),
                ],
            )
        )
        raw_files, total = list_raw_files_by_user(session, user_id="user_a", limit=100, offset=0)
        links = list(session.exec(select(SubjectFileLink)).all())

    assert total == 1
    assert len(raw_files) == 1
    assert len(links) == 1
    assert len(fake_store.writes) == 1
    assert parse_ids == [raw_files[0].id]
    assert data.started_parse_count == 1
    assert len(data.uploaded_items) == 2
    assert data.uploaded_items[0].uid == data.uploaded_items[1].uid
