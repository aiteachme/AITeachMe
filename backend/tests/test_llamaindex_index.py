from __future__ import annotations

import asyncio
import sys
import types

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import app.repositories.knowledge.knowledge_repo as knowledge_repo
import app.shared.infra.search.api as search_api
from app.models import RawFile, RetrievalChunk, Subject, User
from app.shared.infra.search.llamaindex_index import manager
from app.shared.infra.search.llamaindex_index import (
    IndexedChunk,
    clear_subject_index,
    count_indexed_chunks,
    delete_chunks,
    query_subject_index,
    subject_index_exists,
    upsert_chunks,
)


class _MemoryContentStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def read_text(self, key: str, *, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def write_text(self, key: str, content: str) -> None:
        self.data[key] = content

    async def exists(self, key: str) -> bool:
        return key in self.data

    async def delete_prefix(self, prefix: str) -> int:
        keys = [key for key in self.data if key.startswith(prefix)]
        for key in keys:
            del self.data[key]
        return len(keys)


def test_local_llamaindex_subject_index_persists_queries_and_deletes(monkeypatch) -> None:
    store = _MemoryContentStore()
    monkeypatch.setattr(manager, "get_content_store", lambda: store)
    monkeypatch.setattr(manager, "is_cloud_mode", lambda: False)

    subject = "subj_llamaindex"
    clear_subject_index(subject)

    upsert_chunks(
        subject,
        [
            IndexedChunk(
                chunk_id=1,
                document_id=10,
                subject=subject,
                title="向量空间",
                header_path="线性代数 / 向量空间",
                content="向量空间包含加法和数乘。",
                embedding=[1.0, 0.0],
            ),
            IndexedChunk(
                chunk_id=2,
                document_id=10,
                subject=subject,
                title="矩阵乘法",
                header_path="线性代数 / 矩阵",
                content="矩阵乘法满足结合律。",
                embedding=[0.0, 1.0],
            ),
        ],
    )

    assert subject_index_exists(subject) is True
    assert count_indexed_chunks(subject, [1, 2, 3]) == 2

    hits = query_subject_index(subject, [1.0, 0.0], top_k=2)
    assert [hit.chunk_id for hit in hits] == [1, 2]

    delete_chunks(subject, [1])

    assert count_indexed_chunks(subject, [1, 2]) == 1
    hits_after_delete = query_subject_index(subject, [1.0, 0.0], top_k=2)
    assert [hit.chunk_id for hit in hits_after_delete] == [2]

    clear_subject_index(subject)

    assert subject_index_exists(subject) is False


def test_local_delete_missing_subject_index_does_not_create_empty_store(monkeypatch) -> None:
    store = _MemoryContentStore()
    monkeypatch.setattr(manager, "get_content_store", lambda: store)
    monkeypatch.setattr(manager, "is_cloud_mode", lambda: False)

    delete_chunks("subj_missing_index", [1])

    assert store.data == {}


def test_search_knowledge_uses_llamaindex_index_end_to_end(monkeypatch) -> None:
    store = _MemoryContentStore()
    monkeypatch.setattr(manager, "get_content_store", lambda: store)
    monkeypatch.setattr(manager, "is_cloud_mode", lambda: False)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(search_api, "get_engine", lambda: engine)

    subject = "subj_search_knowledge"
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id="local", username="local"))
        session.add(Subject(user_id="local", slug=subject, name="测试学科"))
        raw_file = RawFile(
            uid="raw-search-knowledge",
            subject=subject,
            filename="sample.md",
            filetype="md",
            file_path="/tmp/sample.md",
            markdown_content="# sample",
        )
        session.add(raw_file)
        session.commit()
        session.refresh(raw_file)

        chunk = RetrievalChunk(
            subject=subject,
            document_id=int(raw_file.id or 0),
            title="向量空间",
            level=1,
            header_path="线性代数 / 向量空间",
            chunk_index=0,
            content="向量空间包含加法和数乘。",
        )
        session.add(chunk)
        session.commit()
        session.refresh(chunk)

        knowledge_repo.bulk_insert_embeddings(
            session,
            subject=subject,
            chunk_ids=[int(chunk.id or 0)],
            embeddings=[[1.0, 0.0]],
            embedding_model="text-embedding-v4",
        )

    async def fake_notice(_subject: str) -> str | None:
        return None

    async def fake_embed_texts(_texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0]]

    monkeypatch.setattr(search_api, "get_knowledge_search_notice", fake_notice)
    monkeypatch.setattr("app.shared.infra.embedding.aembed_texts", fake_embed_texts)

    chunks = asyncio.run(
        search_api.search_knowledge(
            "什么是向量空间？",
            subject,
            top_k=1,
            enable_rerank=False,
        )
    )

    assert len(chunks) == 1
    assert chunks[0].title == "向量空间"
    assert chunks[0].source == "llamaindex"


def test_cloud_postgres_store_uses_safe_connection_urls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakePGVectorStore:
        @classmethod
        def from_params(cls, **kwargs):
            captured.update(kwargs)
            return cls()

    llama_index_pkg = types.ModuleType("llama_index")
    vector_stores_pkg = types.ModuleType("llama_index.vector_stores")
    postgres_pkg = types.ModuleType("llama_index.vector_stores.postgres")
    postgres_pkg.PGVectorStore = FakePGVectorStore

    monkeypatch.setitem(sys.modules, "llama_index", llama_index_pkg)
    monkeypatch.setitem(sys.modules, "llama_index.vector_stores", vector_stores_pkg)
    monkeypatch.setitem(sys.modules, "llama_index.vector_stores.postgres", postgres_pkg)
    monkeypatch.setattr(manager, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(
        manager,
        "get_env",
        lambda name, default=None: "postgresql+psycopg://user:p%40ss@example.com:5432/atm"
        if name == "DATABASE_URL"
        else default,
    )

    store = manager._load_postgres_store()

    assert isinstance(store, FakePGVectorStore)
    assert captured["connection_string"].drivername == "postgresql+psycopg2"
    assert captured["connection_string"].password == "p@ss"
    assert captured["async_connection_string"].drivername == "postgresql+asyncpg"
    assert captured["table_name"] == "atm_llamaindex_rag"
    assert captured["use_jsonb"] is True


def test_cloud_count_indexed_chunks_is_conservative(monkeypatch) -> None:
    monkeypatch.setattr(manager, "is_cloud_mode", lambda: True)

    assert count_indexed_chunks("subj_cloud", [1, 2]) == 0
