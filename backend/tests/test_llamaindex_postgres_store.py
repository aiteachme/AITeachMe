from __future__ import annotations

import sys
from types import ModuleType

import llama_index
from sqlalchemy.engine import make_url

from app.shared.infra.search.llamaindex_index import manager


def test_postgres_store_preserves_encoded_password_when_switching_drivers(monkeypatch) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_from_params(**kwargs):
        captured.update(kwargs)
        return sentinel

    class FakePGVectorStore:
        from_params = staticmethod(fake_from_params)

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
    assert "***" not in str(captured["connection_string"])
    assert "***" not in str(captured["async_connection_string"])
