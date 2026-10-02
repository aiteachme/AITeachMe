from __future__ import annotations

from contextlib import contextmanager, nullcontext
import sys
from types import ModuleType, SimpleNamespace

import llama_index
import pytest
from sqlalchemy.engine import make_url

from app.shared.infra.course import settings as course_settings
from app.shared.infra import database
from app.shared.infra.search.llamaindex_index import manager


def test_postgres_store_preserves_encoded_password_when_switching_drivers(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    class FakePGVectorStore:
        def __new__(cls, **kwargs):
            captured.update(kwargs)
            return sentinel

    vector_stores_module = ModuleType("llama_index.vector_stores")
    postgres_module = ModuleType("llama_index.vector_stores.postgres")
    postgres_module.PGVectorStore = FakePGVectorStore
    vector_stores_module.postgres = postgres_module
    monkeypatch.setattr(llama_index, "vector_stores", vector_stores_module, raising=False)
    monkeypatch.setitem(sys.modules, "llama_index.vector_stores", vector_stores_module)
    monkeypatch.setitem(sys.modules, "llama_index.vector_stores.postgres", postgres_module)

    monkeypatch.setattr(manager, "_course_store_spec", lambda *_args, **_kwargs: ("course_index", 1536))
    monkeypatch.setattr(
        manager,
        "_sync_database_url",
        lambda: "postgresql+psycopg://postgres:p%40ss%3Aword@db.example:5432/atm",
    )
    result = manager._load_postgres_store(course_id="course-vector", embedding_dim=1536)

    sync_url = make_url(str(captured["connection_string"]))
    async_url = make_url(str(captured["async_connection_string"]))
    assert result is sentinel
    assert sync_url.drivername == "postgresql+psycopg2"
    assert async_url.drivername == "postgresql+asyncpg"
    assert sync_url.password == "p@ss:word"
    assert async_url.password == "p@ss:word"
    assert captured["initialization_fail_on_error"] is True
    assert "***" not in str(captured["connection_string"])
    assert "***" not in str(captured["async_connection_string"])


def test_postgres_course_index_identifiers_fit_server_limit(monkeypatch) -> None:
    monkeypatch.setattr(course_settings, "is_cloud_mode", lambda: True)
    course_id = "course_oiec86hbufup"
    owner_user_id = "guest_" + "x" * 40

    index_name = course_settings.build_postgres_course_index_name(
        course_id,
        owner_user_id=owner_user_id,
    )
    table_name = course_settings.build_postgres_course_index_data_table_name(
        course_id,
        owner_user_id=owner_user_id,
    )
    vector_ref = f"llamaindex://postgres/{index_name}"

    assert len(table_name) <= 63
    assert len(f"{index_name}_idx_1") <= 63
    assert len(f"{table_name}_embedding_idx") <= 63
    assert course_settings.extract_postgres_course_index_data_table_name(vector_ref) == table_name
    assert index_name != course_settings.build_postgres_course_index_name(
        course_id,
        owner_user_id="guest_" + "y" * 40,
    )


def test_legacy_postgres_vector_ref_matches_server_identifier_truncation() -> None:
    legacy_index_name = (
        "atm_llamaindex_rag_guest_xxxxxx_course_oiec86hbu_62daf50bca"
    )
    raw_table_name = f"data_{legacy_index_name}"

    assert len(raw_table_name) == 64
    assert course_settings.extract_postgres_course_index_data_table_name(
        f"llamaindex://postgres/{legacy_index_name}"
    ) == raw_table_name[:63]


def test_upsert_rejects_unverified_vector_write(monkeypatch) -> None:
    class FakeVectorStore:
        def delete_nodes(self, **_kwargs) -> None:
            return None

        def add(self, _nodes) -> None:
            return None

    monkeypatch.setattr(manager, "_course_lock", lambda _course_id: nullcontext())
    monkeypatch.setattr(manager, "_load_store", lambda *_args, **_kwargs: FakeVectorStore())
    monkeypatch.setattr(manager, "list_indexed_chunk_ids", lambda *_args, **_kwargs: set())

    with pytest.raises(RuntimeError, match="expected 1 chunks, found 0"):
        manager.upsert_chunks(
            "course-vector",
            [
                manager.IndexedChunk(
                    chunk_id=101,
                    file_id="file-1",
                    course_id="course-vector",
                    title="Vector checks",
                    header_path="Vector checks",
                    content="Persisted rows must be verified.",
                    embedding=[0.1, 0.2],
                )
            ],
        )


def test_course_index_cloud_write_scope_leaves_application_pool_available(monkeypatch, tmp_path) -> None:
    import sqlalchemy as sa

    engine = sa.create_engine(
        f"sqlite:///{(tmp_path / 'pool.sqlite').as_posix()}",
        pool_size=1, max_overflow=0, pool_timeout=0.1,
    )

    # Exercise real connection checkout while standing in for the PG lock SQL.
    def install_lock_function(connection, _record):
        connection.create_function("pg_advisory_xact_lock", 1, lambda _key: 0)

    sa.event.listen(sa.engine.Engine, "connect", install_lock_function)
    monkeypatch.setattr(manager, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    try:
        with manager.course_index_write_scope("course-pool"):
            with engine.begin() as connection:
                assert connection.execute(sa.text("SELECT 1")).scalar_one() == 1
    finally:
        sa.event.remove(sa.engine.Engine, "connect", install_lock_function)
        engine.dispose()


def test_course_index_cloud_write_scope_is_reentrant_and_releases_on_failure(monkeypatch) -> None:
    opened = closed = 0
    lock_keys = []

    def execute(statement, parameters):
        assert str(statement) == "SELECT pg_advisory_xact_lock(:key)"
        lock_keys.append(parameters["key"])

    @contextmanager
    def transaction():
        nonlocal opened, closed
        opened += 1
        try:
            yield SimpleNamespace(execute=execute)
        finally:
            closed += 1

    monkeypatch.setattr(manager, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(database, "get_engine", lambda: SimpleNamespace(begin=transaction))
    monkeypatch.setattr(manager, "_cloud_index_lock_engine", lambda engine: engine)
    with pytest.raises(RuntimeError, match="failed write"):
        with manager.course_index_write_scope("course-a"):
            with manager.course_index_write_scope(" course-a "):
                assert opened == 1 and closed == 0
                raise RuntimeError("failed write")
    assert opened == closed == 1
    with manager.course_index_write_scope("course-a"):
        assert opened == 2
    with manager.course_index_write_scope("course-b"):
        assert opened == 3
    assert opened == closed == 3
    assert lock_keys[0] == lock_keys[1] != lock_keys[2]
    assert all(-(2 ** 63) <= key < 2 ** 63 for key in lock_keys)
