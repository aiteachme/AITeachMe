from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import Course, CourseFileLink, RawFile
from app.workflows.digest.common import prepare


COURSE_ID = "course_source_test"


@pytest.fixture
def source_database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    @contextmanager
    def transaction():
        # Expiration on commit also checks that loading returns detached data.
        with Session(engine) as session:
            yield session
            session.commit()

    monkeypatch.setattr(prepare, "managed_session", transaction)
    monkeypatch.setattr(prepare, "resolve_course_storage_scope", lambda _: SimpleNamespace(user_id="local"))
    with transaction() as session:
        session.add(Course(id=COURSE_ID, user_id="local", name="Sources"))
    yield transaction
    engine.dispose()


def add_source(session, file_id, content):
    session.add(RawFile(
        id=file_id, user_id="local", filename=f"{file_id}.md", filetype="md",
        file_path=f"{file_id}.md", markdown_content=content,
    ))
    session.add(CourseFileLink(user_id="local", course_id=COURSE_ID, file_id=file_id))


def content_store(read_text):
    scope = SimpleNamespace(
        raw_markdown_key=lambda **kwargs: f"{kwargs['file_id']}.md",
        asset_prefix=lambda **kwargs: f"assets/{kwargs['file_id']}/",
    )
    return SimpleNamespace(user_file_scope=lambda **_: scope, read_text=read_text)


@pytest.mark.anyio
async def test_source_loading_uses_committed_body_and_preserves_requested_order(source_database, monkeypatch):
    with source_database() as session:
        add_source(session, "first", "# Fresh database body\r\nfirst")
        add_source(session, "second", "# Second\nsecond")
    reads = []

    async def unavailable_store(key, **kwargs):
        reads.append(key)
        raise OSError("object store unavailable")

    monkeypatch.setattr(prepare, "get_content_store", lambda: content_store(unavailable_store))
    loop_thread = threading.get_ident()
    list_files = prepare.list_raw_files_by_ids

    def load_in_worker(*args):
        assert threading.get_ident() != loop_thread
        return list_files(*args)

    monkeypatch.setattr(prepare, "list_raw_files_by_ids", load_in_worker)
    packets = await prepare.load_source_packets(COURSE_ID, ["second", "first"])
    assert [packet.file_id for packet in packets] == ["second", "first"]
    assert packets[1].normalized_content == "# Fresh database body\nfirst"
    assert reads == []


@pytest.mark.anyio
async def test_source_loading_bounds_legacy_storage_reads(source_database, monkeypatch):
    file_ids = [f"source-{index}" for index in range(25)]
    with source_database() as session:
        for file_id in file_ids:
            add_source(session, file_id, " \n")
    active = peak = 0
    reads = []

    async def stored_markdown(key, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.002)
            reads.append(key)
            return f"# {key}"
        finally:
            active -= 1

    monkeypatch.setattr(prepare, "get_content_store", lambda: content_store(stored_markdown))
    packets = await prepare.load_source_packets(COURSE_ID, file_ids)
    assert [packet.file_id for packet in packets] == file_ids
    assert len(reads) == 25
    assert 1 < peak <= 8
    assert active == 0


@pytest.mark.anyio
async def test_source_read_failure_cancels_other_reads_before_returning(source_database, monkeypatch):
    file_ids = [f"source-{index}" for index in range(12)]
    with source_database() as session:
        for file_id in file_ids:
            add_source(session, file_id, "")
    active = 0
    cancelled = []

    async def failing_store(key, **kwargs):
        nonlocal active
        active += 1
        try:
            if key == "source-0.md":
                await asyncio.sleep(0)
                raise OSError("storage failure")
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.append(key)
            raise
        finally:
            active -= 1

    monkeypatch.setattr(prepare, "get_content_store", lambda: content_store(failing_store))
    with pytest.raises(OSError, match="storage failure"):
        await prepare.load_source_packets(COURSE_ID, file_ids)
    assert cancelled
    assert active == 0
