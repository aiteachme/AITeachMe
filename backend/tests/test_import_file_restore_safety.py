from __future__ import annotations

import json
from pathlib import Path
import socket

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 - register SQLModel tables
from app.models import RawFile, User
from app.shared.infra import database
from app.shared.infra.database import core as database_core
from app.shared.infra.storage.course_scope import build_file_storage_segment
from app.workflows.support.export_import import imports as import_module


COURSE_ID = "course_restore12345"
USER_ID = "restore-user"


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch: pytest.MonkeyPatch):
    attempts = {"network": 0, "default_database": 0}

    def deny_network(*args, **kwargs):
        attempts["network"] += 1
        raise AssertionError("The test must not access the network")

    def deny_default_database(*args, **kwargs):
        attempts["default_database"] += 1
        raise AssertionError("The test must use its in-memory database")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setattr(database, "get_engine", deny_default_database)
    monkeypatch.setattr(database_core, "get_engine", deny_default_database)
    yield
    assert attempts == {"network": 0, "default_database": 0}


@pytest.fixture
def session():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.add_all([
                User(id=USER_ID, username=USER_ID),
                User(id="other-user", username="other-user"),
            ])
            db.commit()
            yield db
    finally:
        engine.dispose()


class _MemoryStore:
    def __init__(self, keys: list[str]) -> None:
        self.contents = dict.fromkeys(keys, b"existing content")
        self.writes: list[str] = []

    def write_bytes(self, key: str, content: bytes) -> None:
        self.contents[key] = content
        self.writes.append(key)


@pytest.mark.parametrize("scenario", ["unmapped", "other_user", "reused", "new_file"])
def test_import_restores_only_mapped_files_created_for_this_user_and_course(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    old_id = "old-file"
    file_id = old_id if scenario == "unmapped" else "new-file"
    owner = "other-user" if scenario == "other_user" else USER_ID
    origin = "course_other1234567" if scenario == "reused" else COURSE_ID
    prefix = f"users/{owner}/files/{file_id}"
    raw_key = f"{prefix}/raw.md"
    markdown_key = f"{prefix}/markdown.md"
    asset_prefix = f"{prefix}/assets"
    asset_key = f"{asset_prefix}/images/diagram.png"
    session.add(RawFile(
        id=file_id, user_id=owner, origin_course_id=origin,
        filename="source.md", filetype="md", file_path=raw_key,
        markdown_path=markdown_key, asset_dir=asset_prefix,
    ))
    session.commit()

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    (db_dir / "raw_file.json").write_text(
        json.dumps({"records": [{"id": old_id, "filename": "source.md"}]}), encoding="utf-8",
    )
    segment = build_file_storage_segment(file_id=old_id, filename="source.md")
    package_files = {
        tmp_path / "files" / "raw_files" / segment / "raw.md": b"imported raw",
        tmp_path / "files" / "raw_markdowns" / segment / "markdown.md": b"imported markdown",
        tmp_path / "files" / "assets" / segment / "images" / "diagram.png": b"imported asset",
    }
    for path, content in package_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    store = _MemoryStore([raw_key, markdown_key, asset_key])
    monkeypatch.setattr(import_module, "get_content_store", lambda: store)
    monkeypatch.setattr(import_module, "run_store_sync", lambda func, *args, **kwargs: func(*args, **kwargs))
    file_id_map = {} if scenario == "unmapped" else {old_id: file_id}

    import_module._unpack_files(
        session, tmp_path, COURSE_ID, user_id=USER_ID, file_id_map=file_id_map,
    )

    if scenario == "new_file":
        assert store.writes == [raw_key, markdown_key, asset_key]
        assert store.contents == {
            raw_key: b"imported raw", markdown_key: b"imported markdown", asset_key: b"imported asset",
        }
    else:
        assert store.writes == []
        assert set(store.contents.values()) == {b"existing content"}
