from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.shared.infra.config import Settings
from app.shared.infra.search.types import SearchResult
from app.shared.infra.search.web import dispatch_web_search


@dataclass
class FakeRetriever:
    name: str
    results: list[SearchResult]
    delay_s: float = 0.0

    async def traced_search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        del query
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return list(self.results[:max_results])


def _settings() -> Settings:
    return Settings(
        search_parallel_retrievers=True,
        search_max_parallel_retrievers=4,
        search_provider_timeout_s=1.0,
        search_total_timeout_s=3.0,
        search_fusion_k=60,
        local_rag_min_results=2,
    )


def test_dispatch_web_search_runs_external_retrievers_in_parallel(monkeypatch) -> None:
    local = FakeRetriever(
        name="local_rag",
        results=[SearchResult(url="local://chunk/1", title="local", snippet="partial derivative", source="local_rag")],
    )
    slow_a = FakeRetriever(
        name="brave",
        delay_s=0.15,
        results=[SearchResult(url="https://a.example/math", title="A", snippet="surface slice", source="brave")],
    )
    slow_b = FakeRetriever(
        name="exa",
        delay_s=0.15,
        results=[SearchResult(url="https://b.example/math", title="B", snippet="worked examples", source="exa")],
    )

    monkeypatch.setattr("app.shared.infra.search.web.get_settings", _settings)
    monkeypatch.setattr(
        "app.shared.infra.search.factory.get_retrievers_for_subject",
        lambda **_kwargs: [local, slow_a, slow_b],
    )

    started = time.monotonic()
    results = asyncio.run(dispatch_web_search("partial derivative", top_k=3, subject="math"))
    elapsed = time.monotonic() - started

    assert elapsed < 0.28
    assert {item.url for item in results} == {
        "local://chunk/1",
        "https://a.example/math",
        "https://b.example/math",
    }
    assert results[0].url == "local://chunk/1"


def test_dispatch_web_search_fuses_duplicate_urls(monkeypatch) -> None:
    first = FakeRetriever(
        name="brave",
        results=[
            SearchResult(url="https://example.com/math", title="Short", snippet="short", source="brave"),
        ],
    )
    second = FakeRetriever(
        name="exa",
        results=[
            SearchResult(
                url="https://example.com/math",
                title="Long",
                snippet="longer explanation about partial derivatives and surface slices",
                source="exa",
            )
        ],
    )

    monkeypatch.setattr("app.shared.infra.search.web.get_settings", _settings)
    monkeypatch.setattr(
        "app.shared.infra.search.factory.get_retrievers_for_subject",
        lambda **_kwargs: [first, second],
    )

    results = asyncio.run(dispatch_web_search("partial derivative", top_k=5))

    assert len(results) == 1
    assert results[0].url == "https://example.com/math"
    assert "longer explanation" in results[0].snippet
    assert results[0].source == "brave+exa"
