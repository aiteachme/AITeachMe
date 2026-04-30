from __future__ import annotations

import pytest

from app.shared.infra.search.knowledge import RetrievedChunk
from app.shared.infra.search.llamaindex_index import ingestion
from app.shared.infra.search.retrievers import local_rag
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.workflows.digest.common import section_splitter


@pytest.mark.anyio
async def test_local_rag_prefers_vector_results_when_available(monkeypatch) -> None:
    async def fake_notice(course_id: str) -> str | None:
        assert course_id == "course_math"
        return None

    async def fake_search_knowledge(query: str, course_id: str, *, top_k: int):
        assert query == "隐函数求导"
        assert course_id == "course_math"
        assert top_k == 6
        return [
            RetrievedChunk(
                chunk_id=7,
                file_id="file_1",
                title="隐函数",
                header_path="导数 > 隐函数",
                content="隐函数求导需要两边同时对自变量求导。",
                score=0.92,
                source="vector",
            )
        ]

    monkeypatch.setattr(local_rag, "get_knowledge_search_notice", fake_notice)
    monkeypatch.setattr(local_rag, "search_knowledge", fake_search_knowledge)

    retriever = LocalRAGRetriever(
        course_id="course_math",
        local_sections=[
            {
                "title": "隐函数",
                "normalized_content": "隐函数求导的关键词命中内容。",
            }
        ],
    )

    results = await retriever.search("隐函数求导", max_results=3)

    assert results
    assert results[0].url == "local://chunk/7"
    assert any(item.url.startswith("local://section/") for item in results)


@pytest.mark.anyio
async def test_local_rag_uses_sections_only_when_vector_unavailable(monkeypatch) -> None:
    async def fake_notice(course_id: str) -> str | None:
        assert course_id == "course_math"
        return "vector index unavailable"

    async def fake_search_knowledge(*args, **kwargs):
        raise AssertionError("vector search should be bypassed")

    monkeypatch.setattr(local_rag, "get_knowledge_search_notice", fake_notice)
    monkeypatch.setattr(local_rag, "search_knowledge", fake_search_knowledge)

    retriever = LocalRAGRetriever(
        course_id="course_math",
        local_sections=[
            {
                "title": "极限",
                "normalized_content": "极限的夹逼准则可以用于证明数列收敛。",
            }
        ],
    )

    results = await retriever.search("夹逼准则", max_results=2)

    assert len(results) == 1
    assert results[0].url == "local://section/0"


def test_large_section_splitting_delegates_to_llamaindex(monkeypatch) -> None:
    monkeypatch.setattr(
        section_splitter,
        "split_text_for_ingestion",
        lambda text: ["第一段", "第二段"],
    )

    packets = section_splitter.split_into_sections(
        "很长的内容。" * 400,
        file_id="file_1",
        filename="notes.md",
    )

    assert [packet.normalized_content for packet in packets] == ["第一段", "第二段"]
    assert packets[0].title == "notes (Part 1)"
    assert packets[1].title == "notes (Part 2)"


@pytest.mark.anyio
async def test_ingestion_embedding_count_mismatch_soft_fails(monkeypatch) -> None:
    class FakeEmbedding:
        def __init__(self, *, model_name=None):
            self.model_name = model_name

        async def aget_text_embedding_batch(self, texts):
            return [[0.1, 0.2]]

    monkeypatch.setattr(ingestion, "ATMEmbedding", FakeEmbedding)

    embeddings = await ingestion.aembed_texts_for_ingestion(
        ["one", "two"],
        model="fake-model",
        soft_fail=True,
    )

    assert embeddings == []
