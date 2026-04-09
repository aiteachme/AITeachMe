from __future__ import annotations

import asyncio

from app.shared.infra.config import Settings
from app.shared.infra.search.factory import (
    get_configured_retriever_names,
    get_retrievers_for_subject,
)
from app.shared.infra.search.retrievers.arxiv import ArxivRetriever
from app.shared.infra.search.retrievers.semantic_scholar import SemanticScholarRetriever
from app.shared.infra.search.retrievers.tavily import TavilyRetriever


def test_settings_parse_retrievers_prefers_explicit_list_and_dedupes() -> None:
    settings = Settings(
        _env_file=None,
        web_search_retrievers="tavily, bocha, tavily",
        web_search_retriever_profile="docgen_academic",
        web_search_retriever="bing",
        local_rag_priority=True,
    )

    assert settings.parse_retrievers() == [
        "local_rag",
        "tavily",
        "bocha",
        "duckduckgo",
    ]


def test_settings_parse_retrievers_can_exclude_local_rag_from_profile() -> None:
    settings = Settings(
        _env_file=None,
        web_search_retriever_profile="docgen_academic",
        local_rag_priority=False,
    )

    assert settings.parse_retrievers(include_local_rag=False) == [
        "tavily",
        "arxiv",
        "semantic_scholar",
        "duckduckgo",
    ]


def test_get_configured_retriever_names_filters_unknown_names(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        web_search_retrievers="tavily, unknown_one, bocha",
        local_rag_priority=False,
    )
    monkeypatch.setattr("app.shared.infra.search.factory.get_settings", lambda: settings)

    assert get_configured_retriever_names(include_local_rag=False) == [
        "tavily",
        "bocha",
        "duckduckgo",
    ]


def test_get_configured_retriever_names_keeps_academic_profile_retrievers(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        web_search_retriever_profile="docgen_academic",
        local_rag_priority=False,
    )
    monkeypatch.setattr("app.shared.infra.search.factory.get_settings", lambda: settings)

    assert get_configured_retriever_names(include_local_rag=False) == [
        "tavily",
        "arxiv",
        "semantic_scholar",
        "duckduckgo",
    ]


def test_get_retrievers_for_subject_includes_local_rag_when_context_exists(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        web_search_retrievers="tavily, duckduckgo",
        local_rag_priority=True,
    )
    monkeypatch.setattr("app.shared.infra.search.factory.get_settings", lambda: settings)

    retrievers = get_retrievers_for_subject(subject="math")

    assert [item.name for item in retrievers] == [
        "local_rag",
        "tavily",
        "duckduckgo",
    ]


def test_get_retrievers_for_subject_skips_local_rag_without_context(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        web_search_retrievers="tavily, duckduckgo",
        local_rag_priority=True,
    )
    monkeypatch.setattr("app.shared.infra.search.factory.get_settings", lambda: settings)

    retrievers = get_retrievers_for_subject()

    assert [item.name for item in retrievers] == [
        "tavily",
        "duckduckgo",
    ]


def test_tavily_retriever_maps_results(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "results": [
                    {
                        "url": "https://example.com/math",
                        "title": "Partial Derivative",
                        "content": "A surface slice explains the geometric meaning.",
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout: int) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, object]) -> FakeResponse:
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

    settings = Settings(_env_file=None, tavily_api_key="secret", search_scrape_timeout_s=9)
    monkeypatch.setattr("app.shared.infra.search.retrievers.tavily.get_settings", lambda: settings)
    monkeypatch.setattr("app.shared.infra.search.retrievers.tavily.httpx.AsyncClient", FakeAsyncClient)

    results = asyncio.run(TavilyRetriever().search("partial derivative", max_results=3))

    assert len(results) == 1
    assert results[0].url == "https://example.com/math"
    assert results[0].source == "tavily"
    assert captured["timeout"] == 9
    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["payload"]["query"] == "partial derivative"
    assert captured["payload"]["max_results"] == 3


def test_arxiv_retriever_maps_atom_feed(monkeypatch) -> None:
    class FakeResponse:
        text = """
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>https://arxiv.org/abs/1234.5678</id>
            <title>Partial Derivatives and Geometry</title>
            <summary>Explains the geometric meaning of partial derivatives.</summary>
            <link href="https://arxiv.org/pdf/1234.5678.pdf" rel="related" type="application/pdf" title="pdf" />
          </entry>
        </feed>
        """

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *, timeout: int) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert "partial+derivative" in url
            return FakeResponse()

    settings = Settings(_env_file=None, search_scrape_timeout_s=7)
    monkeypatch.setattr("app.shared.infra.search.retrievers.arxiv.get_settings", lambda: settings)
    monkeypatch.setattr("app.shared.infra.search.retrievers.arxiv.httpx.AsyncClient", FakeAsyncClient)

    results = asyncio.run(ArxivRetriever().search("partial derivative", max_results=2))

    assert len(results) == 1
    assert results[0].url == "https://arxiv.org/pdf/1234.5678.pdf"
    assert results[0].source == "arxiv"
    assert "geometric meaning" in results[0].snippet


def test_semantic_scholar_retriever_maps_results(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [
                    {
                        "title": "Understanding Partial Derivatives",
                        "abstract": "A concise explanation of partial derivatives.",
                        "url": "https://semanticscholar.org/paper/demo",
                        "venue": "DemoConf",
                        "year": 2024,
                        "isOpenAccess": True,
                        "openAccessPdf": {"url": "https://example.com/paper.pdf"},
                    }
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout: int) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str, *, params: dict[str, object], headers: dict[str, str]) -> FakeResponse:
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return FakeResponse()

    settings = Settings(_env_file=None, semantic_scholar_api_key="demo-key", search_scrape_timeout_s=11)
    monkeypatch.setattr("app.shared.infra.search.retrievers.semantic_scholar.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.shared.infra.search.retrievers.semantic_scholar.httpx.AsyncClient",
        FakeAsyncClient,
    )

    results = asyncio.run(SemanticScholarRetriever().search("partial derivative", max_results=4))

    assert len(results) == 1
    assert results[0].url == "https://example.com/paper.pdf"
    assert results[0].source == "semantic_scholar"
    assert captured["url"] == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert captured["params"]["query"] == "partial derivative"
    assert captured["params"]["limit"] == 4
    assert captured["headers"]["x-api-key"] == "demo-key"
