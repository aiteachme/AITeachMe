from __future__ import annotations

import asyncio

import pytest

from app.shared.infra.search.knowledge import RetrievedChunk
from app.shared.infra.search.llamaindex_index import ingestion
from app.shared.infra.search.local_sufficiency import effective_local_result_count
from app.shared.infra.search.retrievers import local_rag
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.types import SearchResult
from app.shared.infra.search.web import dispatch_web_search
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
    assert results[0].score > 0.55
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


def test_effective_local_result_count_ignores_weak_hits() -> None:
    results = [
        SearchResult(url="local://chunk/1", title="弱命中", snippet="noise", score=0.35, source="local_rag"),
        SearchResult(url="local://chunk/2", title="强命中", snippet="useful", score=0.8, source="local_rag"),
        SearchResult(url="https://example.com", title="外部", snippet="web", score=1.0, source="duckduckgo"),
    ]

    assert effective_local_result_count(results) == 1


@pytest.mark.anyio
async def test_dispatch_web_search_continues_when_local_hits_are_weak(monkeypatch) -> None:
    class FakeRetriever:
        def __init__(self, name: str, results: list[SearchResult]) -> None:
            self.name = name
            self.results = results
            self.called = False

        async def traced_search(self, query: str, *, max_results: int) -> list[SearchResult]:
            self.called = True
            return self.results[:max_results]

    local = FakeRetriever(
        "local_rag",
        [
            SearchResult(url="local://chunk/1", title="弱命中 1", snippet="noise", score=0.2, source="local_rag"),
            SearchResult(url="local://chunk/2", title="弱命中 2", snippet="noise", score=0.25, source="local_rag"),
        ],
    )
    external = FakeRetriever(
        "duckduckgo",
        [
            SearchResult(
                url="https://example.com/strong",
                title="外部强命中",
                snippet="useful",
                score=1.0,
                source="duckduckgo",
            )
        ],
    )

    def fake_retrievers_for_course(**kwargs):
        return [local, external]

    monkeypatch.setattr(
        "app.shared.infra.search.factory.get_retrievers_for_course",
        fake_retrievers_for_course,
    )

    results = await dispatch_web_search(
        "测试查询",
        top_k=2,
        total_timeout_s=5,
        provider_timeout_s=1,
    )

    assert local.called
    assert external.called
    assert any(item.url == "https://example.com/strong" for item in results)


@pytest.mark.anyio
async def test_traced_retriever_cancellation_is_recorded_as_empty_result() -> None:
    class CancelledRetriever(BaseRetriever):
        canonical_name = "cancelled_test"
        auto_register = False
        cacheable = False

        async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
            raise asyncio.CancelledError()

    payload = await CancelledRetriever()._run_traced_search("测试查询", max_results=2)

    assert payload["results"] == []
    assert payload["trace"]["cancelled"] is True
    assert payload["trace"]["result_count"] == 0


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
