from __future__ import annotations

import asyncio
from types import SimpleNamespace

import sqlalchemy as sa


def test_cloud_subject_index_ref_is_user_subject_scoped(monkeypatch) -> None:
    from app.shared.infra.subject import settings as subject_settings

    monkeypatch.setattr(subject_settings, "is_cloud_mode", lambda: True)

    math_ref = subject_settings.build_subject_index_ref("math", owner_user_id="user_a")
    physics_ref = subject_settings.build_subject_index_ref("math", owner_user_id="user_b")

    assert math_ref != physics_ref
    assert math_ref.startswith("llamaindex://postgres/atm_llamaindex_rag_")
    assert physics_ref.startswith("llamaindex://postgres/atm_llamaindex_rag_")
    assert (
        subject_settings.extract_postgres_subject_index_data_table_name(math_ref)
        == f"data_{subject_settings.extract_postgres_subject_index_name(math_ref)}"
    )


def test_local_subject_index_ref_is_user_subject_scoped(monkeypatch) -> None:
    from app.shared.infra.subject import settings as subject_settings

    monkeypatch.setattr(subject_settings, "is_cloud_mode", lambda: False)

    ref = subject_settings.build_subject_index_ref("math", owner_user_id="user_a")

    assert ref == "llamaindex://sqlite-vec/users/user_a/subjects/math/rag_index"


def test_local_vector_capability_uses_local_index_existence(monkeypatch) -> None:
    from app.models.subject import Subject
    from app.shared.infra.subject import vectors
    from app.shared.infra.subject.settings import build_enabled_binding, set_subject_embedding_binding

    subject = Subject(user_id="user_a", slug="math", name="Math")
    set_subject_embedding_binding(
        subject,
        build_enabled_binding(
            subject_slug=subject.slug,
            owner_user_id=subject.user_id,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )

    monkeypatch.setattr(vectors, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(
        vectors,
        "get_runtime_embedding_config",
        lambda: vectors.RuntimeEmbeddingConfig(
            configured=True,
            available=True,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )

    import app.shared.infra.search.llamaindex_index as llamaindex_index

    monkeypatch.setattr(llamaindex_index, "subject_index_exists", lambda slug: slug == "math")

    capability = vectors.get_subject_vector_capability(SimpleNamespace(), subject)

    assert capability.queryable is True
    assert capability.status.notice is None


def test_should_generate_embeddings_when_bound_local_index_is_missing(monkeypatch) -> None:
    from app.models.subject import Subject
    from app.shared.infra.subject import vectors
    from app.shared.infra.subject.settings import build_enabled_binding, set_subject_embedding_binding

    subject = Subject(user_id="user_a", slug="math", name="Math")
    set_subject_embedding_binding(
        subject,
        build_enabled_binding(
            subject_slug=subject.slug,
            owner_user_id=subject.user_id,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )

    monkeypatch.setattr(vectors, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(vectors, "get_subject_record_by_slug", lambda session, subject_slug: subject)
    monkeypatch.setattr(
        vectors,
        "get_runtime_embedding_config",
        lambda: vectors.RuntimeEmbeddingConfig(
            configured=True,
            available=True,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )

    import app.shared.infra.search.llamaindex_index as llamaindex_index

    monkeypatch.setattr(llamaindex_index, "subject_index_exists", lambda slug: False)
    monkeypatch.setattr(vectors, "subject_has_retrieval_chunks", lambda session, subject_slug: True)

    capability = vectors.get_subject_vector_capability(SimpleNamespace(), subject)

    assert capability.queryable is False
    assert capability.writable is True
    assert vectors.should_generate_subject_embeddings(SimpleNamespace(), subject_slug="math") is True


def test_missing_local_index_without_chunks_is_not_precheck_notice(monkeypatch) -> None:
    from app.models.subject import Subject
    from app.shared.infra.subject import vectors
    from app.shared.infra.subject.settings import build_enabled_binding, set_subject_embedding_binding

    subject = Subject(user_id="user_a", slug="math", name="Math")
    set_subject_embedding_binding(
        subject,
        build_enabled_binding(
            subject_slug=subject.slug,
            owner_user_id=subject.user_id,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )

    monkeypatch.setattr(vectors, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(
        vectors,
        "get_runtime_embedding_config",
        lambda: vectors.RuntimeEmbeddingConfig(
            configured=True,
            available=True,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )

    import app.shared.infra.search.llamaindex_index as llamaindex_index

    monkeypatch.setattr(llamaindex_index, "subject_index_exists", lambda slug: False)
    monkeypatch.setattr(vectors, "subject_has_retrieval_chunks", lambda session, subject_slug: False)

    capability = vectors.get_subject_vector_capability(SimpleNamespace(), subject)

    assert capability.queryable is False
    assert capability.writable is True
    assert capability.status.notice is None


def test_legacy_local_ref_without_chunks_is_not_precheck_notice(monkeypatch) -> None:
    from app.models.subject import Subject
    from app.shared.infra.subject import vectors
    from app.shared.infra.subject.settings import SubjectEmbeddingBinding, set_subject_embedding_binding

    subject = Subject(user_id="user_a", slug="math", name="Math")
    set_subject_embedding_binding(
        subject,
        SubjectEmbeddingBinding(
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
            vector_table="llamaindex://local/users/user_a/subjects/math/rag_index",
        ),
    )

    monkeypatch.setattr(vectors, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(
        vectors,
        "get_runtime_embedding_config",
        lambda: vectors.RuntimeEmbeddingConfig(
            configured=True,
            available=True,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )
    monkeypatch.setattr(vectors, "subject_has_retrieval_chunks", lambda session, subject_slug: False)

    capability = vectors.get_subject_vector_capability(SimpleNamespace(), subject)

    assert capability.queryable is False
    assert capability.writable is True
    assert capability.status.notice is None


def test_legacy_local_ref_with_chunks_still_allows_embedding_write(monkeypatch) -> None:
    from app.models.subject import Subject
    from app.shared.infra.subject import vectors
    from app.shared.infra.subject.settings import SubjectEmbeddingBinding, set_subject_embedding_binding

    subject = Subject(user_id="user_a", slug="math", name="Math")
    set_subject_embedding_binding(
        subject,
        SubjectEmbeddingBinding(
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
            vector_table="llamaindex://local/users/user_a/subjects/math/rag_index",
        ),
    )

    monkeypatch.setattr(vectors, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(vectors, "get_subject_record_by_slug", lambda session, subject_slug: subject)
    monkeypatch.setattr(
        vectors,
        "get_runtime_embedding_config",
        lambda: vectors.RuntimeEmbeddingConfig(
            configured=True,
            available=True,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )
    monkeypatch.setattr(vectors, "subject_has_retrieval_chunks", lambda session, subject_slug: True)

    capability = vectors.get_subject_vector_capability(SimpleNamespace(), subject)

    assert capability.queryable is False
    assert capability.writable is True
    assert capability.status.notice == vectors.SUBJECT_VECTOR_PRECHECK_DETAIL_MAP["vector_table_missing"]
    assert vectors.should_generate_subject_embeddings(SimpleNamespace(), subject_slug="math") is True


def test_precheck_allows_missing_index_when_subject_has_no_chunks(monkeypatch) -> None:
    from app.models.subject import Subject
    from app.shared.infra.subject import build_precheck, vectors
    from app.shared.infra.subject.settings import build_enabled_binding, set_subject_embedding_binding

    subject = Subject(user_id="user_a", slug="math", name="Math")
    set_subject_embedding_binding(
        subject,
        build_enabled_binding(
            subject_slug=subject.slug,
            owner_user_id=subject.user_id,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )

    monkeypatch.setattr(build_precheck, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(
        build_precheck,
        "get_runtime_embedding_config",
        lambda: vectors.RuntimeEmbeddingConfig(
            configured=True,
            available=True,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )
    monkeypatch.setattr(
        build_precheck,
        "subject_has_retrieval_chunks",
        lambda session, subject_slug: False,
    )

    import app.shared.infra.search.llamaindex_index as llamaindex_index

    monkeypatch.setattr(llamaindex_index, "subject_index_exists", lambda slug: False)

    assert build_precheck.inspect_subject_build_precheck(SimpleNamespace(), subject=subject) is None


def test_precheck_allows_legacy_local_ref_when_subject_has_no_chunks(monkeypatch) -> None:
    from app.models.subject import Subject
    from app.shared.infra.subject import build_precheck, vectors
    from app.shared.infra.subject.settings import SubjectEmbeddingBinding, set_subject_embedding_binding

    subject = Subject(user_id="user_a", slug="math", name="Math")
    set_subject_embedding_binding(
        subject,
        SubjectEmbeddingBinding(
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
            vector_table="llamaindex://local/users/user_a/subjects/math/rag_index",
        ),
    )

    monkeypatch.setattr(
        build_precheck,
        "get_runtime_embedding_config",
        lambda: vectors.RuntimeEmbeddingConfig(
            configured=True,
            available=True,
            embedding_model="text-embedding-v4",
            embedding_dim=1024,
        ),
    )
    monkeypatch.setattr(
        build_precheck,
        "subject_has_retrieval_chunks",
        lambda session, subject_slug: False,
    )

    assert build_precheck.inspect_subject_build_precheck(SimpleNamespace(), subject=subject) is None


def test_local_sqlite_vec_store_roundtrip(monkeypatch, tmp_path) -> None:
    from llama_index.core.schema import TextNode
    from llama_index.core.vector_stores.types import VectorStoreQuery

    from app.shared.infra.search.llamaindex_index import sqlite_vec_store

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'vec.db'}")
    monkeypatch.setattr(sqlite_vec_store, "get_engine", lambda: engine)

    store = sqlite_vec_store.SQLiteVecVectorStore(subject="math", embedding_dim=3)
    store.add(
        [
            TextNode(
                id_="1",
                text="linear equations",
                embedding=[1.0, 0.0, 0.0],
                metadata={"subject": "math"},
            ),
            TextNode(
                id_="2",
                text="triangle geometry",
                embedding=[0.0, 1.0, 0.0],
                metadata={"subject": "math"},
            ),
        ]
    )

    result = store.query(
        VectorStoreQuery(
            query_embedding=[1.0, 0.0, 0.0],
            similarity_top_k=2,
        )
    )

    assert result.ids == ["1", "2"]
    assert store.subject_has_rows() is True
    assert store.count_node_ids(["1", "2", "999"]) == 2

    store.delete_nodes(node_ids=["1"])
    assert store.count_node_ids(["1", "2"]) == 1

    store.clear()
    assert store.subject_has_rows() is False


def test_local_manager_roundtrip_uses_sqlite_vec(monkeypatch, tmp_path) -> None:
    from app.shared.infra.search.llamaindex_index import manager, sqlite_vec_store

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'manager_vec.db'}")
    monkeypatch.setattr(manager, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(sqlite_vec_store, "get_engine", lambda: engine)

    manager.upsert_chunks(
        "math",
        [
            manager.IndexedChunk(
                chunk_id=1,
                document_id=11,
                subject="math",
                title="A",
                header_path="A",
                content="alpha",
                embedding=[1.0, 0.0, 0.0],
            ),
            manager.IndexedChunk(
                chunk_id=2,
                document_id=11,
                subject="math",
                title="B",
                header_path="B",
                content="beta",
                embedding=[0.0, 1.0, 0.0],
            ),
        ],
    )

    assert manager.subject_index_exists("math") is True
    assert manager.count_indexed_chunks("math", [1, 2, 3]) == 2
    assert [hit.chunk_id for hit in manager.query_subject_index("math", [1.0, 0.0, 0.0], top_k=2)] == [1, 2]

    manager.delete_chunks("math", [1])
    assert manager.count_indexed_chunks("math", [1, 2]) == 1

    manager.clear_subject_index("math")
    assert manager.subject_index_exists("math") is False


def test_upsert_chunks_cloud_uses_subject_scoped_store_and_actual_dimension(
    monkeypatch,
) -> None:
    from app.shared.infra.search.llamaindex_index import manager

    captured: dict[str, object] = {}

    class FakeStore:
        def delete_nodes(self, **kwargs) -> None:
            captured["delete_kwargs"] = kwargs

        def add(self, nodes) -> None:
            captured["node_count"] = len(nodes)

    monkeypatch.setattr(manager, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(
        manager,
        "_load_store",
        lambda subject, *, embedding_dim=None: (
            captured.update(
                {
                    "subject": subject,
                    "embedding_dim": embedding_dim,
                }
            )
            or FakeStore()
        ),
    )

    manager.upsert_chunks(
        "math",
        [
            manager.IndexedChunk(
                chunk_id=1,
                document_id=11,
                subject="math",
                title="A",
                header_path="A",
                content="content-a",
                embedding=[0.1, 0.2, 0.3, 0.4],
            ),
            manager.IndexedChunk(
                chunk_id=2,
                document_id=12,
                subject="math",
                title="B",
                header_path="B",
                content="content-b",
                embedding=[0.5, 0.6, 0.7, 0.8],
            ),
        ],
    )

    assert captured["subject"] == "math"
    assert captured["embedding_dim"] == 4
    assert captured["node_count"] == 2


def test_query_subject_index_cloud_uses_query_vector_dimension(monkeypatch) -> None:
    from app.shared.infra.search.llamaindex_index import manager

    captured: dict[str, object] = {}

    class FakeResult:
        ids = ["1"]
        similarities = [0.91]

    class FakeStore:
        def query(self, query):
            captured["query_embedding"] = list(query.query_embedding or [])
            captured["top_k"] = query.similarity_top_k
            return FakeResult()

    monkeypatch.setattr(manager, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(manager, "subject_index_exists", lambda subject: True)
    monkeypatch.setattr(
        manager,
        "_subject_binding_snapshot",
        lambda subject: SimpleNamespace(embedding_dim=3, vector_table="llamaindex://postgres/demo"),
    )
    monkeypatch.setattr(
        manager,
        "_load_store",
        lambda subject, *, embedding_dim=None: (
            captured.update(
                {
                    "subject": subject,
                    "embedding_dim": embedding_dim,
                }
            )
            or FakeStore()
        ),
    )

    hits = manager.query_subject_index("math", [0.1, 0.2, 0.3], top_k=2)

    assert captured["subject"] == "math"
    assert captured["embedding_dim"] == 3
    assert captured["query_embedding"] == [0.1, 0.2, 0.3]
    assert captured["top_k"] == 2
    assert len(hits) == 1
    assert hits[0].chunk_id == 1


def test_clear_subject_index_cloud_drops_subject_scoped_table(monkeypatch) -> None:
    from app.shared.infra.search.llamaindex_index import manager
    import app.shared.infra.database as database

    captured: dict[str, str] = {}

    class FakeConnection:
        def execute(self, statement):
            captured["sql"] = str(statement)

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    monkeypatch.setattr(manager, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(manager, "subject_index_exists", lambda subject: True)
    monkeypatch.setattr(
        manager,
        "_subject_record_snapshot",
        lambda subject: SimpleNamespace(slug="math", user_id="user_a"),
    )
    monkeypatch.setattr(
        manager,
        "build_subject_index_ref_for_subject",
        lambda subject: "llamaindex://postgres/atm_llamaindex_rag_user_math_abc123",
    )
    monkeypatch.setattr(database, "get_engine", lambda: FakeEngine())

    manager.clear_subject_index("math")

    assert captured["sql"].startswith("DROP TABLE IF EXISTS public.data_atm_llamaindex_rag_")


def test_retrieve_subject_chunks_uses_subject_binding_model(monkeypatch) -> None:
    from app.shared.infra.search.llamaindex_index import manager
    import app.shared.infra.embedding as embedding_pkg

    captured: dict[str, object] = {}

    async def fake_aembed_texts(texts, *, batch_size=None, model=None, soft_fail=False):
        del batch_size, soft_fail
        captured["texts"] = list(texts)
        captured["model"] = model
        return [[0.3, 0.2, 0.1]]

    monkeypatch.setattr(
        manager,
        "_subject_binding_snapshot",
        lambda subject: SimpleNamespace(
            embedding_model="subject-embedding-model",
            embedding_dim=3,
            vector_table="llamaindex://postgres/demo",
        ),
    )
    monkeypatch.setattr(embedding_pkg, "aembed_texts", fake_aembed_texts)
    monkeypatch.setattr(
        manager,
        "query_subject_index",
        lambda subject, query_embedding, *, top_k=5: [],
    )

    hits = asyncio.run(manager.retrieve_subject_chunks("math", "什么是集合", top_k=3))

    assert hits == []
    assert captured["texts"] == ["什么是集合"]
    assert captured["model"] == "subject-embedding-model"
