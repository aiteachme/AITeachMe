from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.shared.infra.config import Settings
from app.shared.infra.search import ContextCompressor, reset_search_runtime_caches
from app.shared.infra.search.readers.base import BaseReader
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.execution import TracedExecutionContext


class DummyCachedRetriever(BaseRetriever):
    auto_register = False
    canonical_name = "dummy_cached"

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.calls += 1
        return [
            SearchResult(
                url=f"https://example.com/{self.calls}",
                title=query,
                snippet=f"call:{self.calls}",
                source=self.name,
            )
        ][:max_results]


class DummyCachedReader(BaseReader):
    auto_register = False
    canonical_name = "dummy_cached_reader"

    def __init__(self) -> None:
        self.calls = 0

    async def read(self, url: str) -> ScrapedPage:
        self.calls += 1
        return ScrapedPage(
            url=url,
            title=f"page:{self.calls}",
            content=f"content:{self.calls}",
            success=True,
        )


def _enabled_cache_settings() -> Settings:
    return Settings(
        search_runtime_cache_enabled=True,
        search_runtime_cache_ttl_s=3600,
        search_runtime_cache_max_entries=32,
    )


def test_retriever_runtime_cache_reuses_external_results(monkeypatch) -> None:
    monkeypatch.setattr("app.shared.infra.search.cache.get_settings", _enabled_cache_settings)
    reset_search_runtime_caches()
    retriever = DummyCachedRetriever()

    async def run_twice() -> tuple[list[SearchResult], list[SearchResult]]:
        first = await retriever.traced_search("partial derivative", max_results=2)
        second = await retriever.traced_search("partial derivative", max_results=2)
        return first, second

    first, second = asyncio.run(run_twice())

    assert retriever.calls == 1
    assert first[0].title == second[0].title == "partial derivative"
    assert first[0].snippet == second[0].snippet == "call:1"


def test_reader_runtime_cache_reuses_url_reads(monkeypatch) -> None:
    monkeypatch.setattr("app.shared.infra.search.cache.get_settings", _enabled_cache_settings)
    reset_search_runtime_caches()
    reader = DummyCachedReader()

    async def run_twice() -> tuple[ScrapedPage, ScrapedPage]:
        first = await reader.traced_read("https://example.com/math")
        second = await reader.traced_read("https://example.com/math")
        return first, second

    first, second = asyncio.run(run_twice())

    assert reader.calls == 1
    assert first.title == second.title == "page:1"
    assert first.content == second.content == "content:1"


def test_context_compressor_runtime_cache_reuses_compression_result(monkeypatch) -> None:
    monkeypatch.setattr("app.shared.infra.search.cache.get_settings", _enabled_cache_settings)
    reset_search_runtime_caches()
    calls = {"embed": 0}

    relevant_doc = "# Partial Derivative\n\n" + ("partial derivative gradient directional derivative surface slice " * 120)
    irrelevant_doc = "# Probability\n\n" + ("random variable probability distribution bayes theorem " * 120)

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        calls["embed"] += 1
        embeddings: list[list[float]] = []
        for text in texts:
            if "partial derivative" in text or "gradient" in text or "surface slice" in text:
                embeddings.append([1.0, 0.0])
            else:
                embeddings.append([0.0, 1.0])
        return embeddings

    manager = ContextCompressor(TracedExecutionContext(subject="demo"))
    with patch("app.shared.infra.search.context_compression.aembed_texts", new=fake_embed_texts):
        first = asyncio.run(
            manager.run(
                query="partial derivative",
                focus_terms=["gradient", "surface slice"],
                documents=[relevant_doc, irrelevant_doc],
                max_results=2,
            )
        )
        second = asyncio.run(
            manager.run(
                query="partial derivative",
                focus_terms=["gradient", "surface slice"],
                documents=[relevant_doc, irrelevant_doc],
                max_results=2,
            )
        )

    assert calls["embed"] == 1
    assert first.metadata["compression_mode"] == "embedding_filter"
    assert first.metadata["cache_hit"] is False
    assert first.metadata["cache_status"] == "miss"
    assert second.metadata["cache_hit"] is True
    assert second.metadata["cache_status"] == "hit"
    assert second.content == first.content