from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_cloud_subject_index_ref_is_subject_scoped(monkeypatch) -> None:
    from app.shared.infra.subject import settings as subject_settings

    monkeypatch.setattr(subject_settings, "is_cloud_mode", lambda: True)

    math_ref = subject_settings.build_subject_index_ref("math")
    physics_ref = subject_settings.build_subject_index_ref("physics")

    assert math_ref != physics_ref
    assert math_ref.startswith("llamaindex://postgres/atm_llamaindex_rag_")
    assert physics_ref.startswith("llamaindex://postgres/atm_llamaindex_rag_")
    assert (
        subject_settings.extract_postgres_subject_index_data_table_name(math_ref)
        == f"data_{subject_settings.extract_postgres_subject_index_name(math_ref)}"
    )


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
        lambda subject, *, embedding_dim=None, use_active_binding=True: (
            captured.update(
                {
                    "subject": subject,
                    "embedding_dim": embedding_dim,
                    "use_active_binding": use_active_binding,
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
    assert captured["use_active_binding"] is False
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
        lambda subject, *, embedding_dim=None, use_active_binding=True: (
            captured.update(
                {
                    "subject": subject,
                    "embedding_dim": embedding_dim,
                    "use_active_binding": use_active_binding,
                }
            )
            or FakeStore()
        ),
    )

    hits = manager.query_subject_index("math", [0.1, 0.2, 0.3], top_k=2)

    assert captured["subject"] == "math"
    assert captured["embedding_dim"] == 3
    assert captured["use_active_binding"] is True
    assert captured["query_embedding"] == [0.1, 0.2, 0.3]
    assert captured["top_k"] == 2
    assert len(hits) == 1
    assert hits[0].chunk_id == 1


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
