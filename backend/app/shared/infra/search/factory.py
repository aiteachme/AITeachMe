"""Retriever factory helpers."""

from __future__ import annotations

from app.shared.infra.config import get_settings
from app.shared.infra.search.retrievers.arxiv import ArxivRetriever
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.bing import BingRetriever
from app.shared.infra.search.retrievers.bocha import BochaRetriever
from app.shared.infra.search.retrievers.duckduckgo import DuckDuckGoRetriever
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.retrievers.semantic_scholar import SemanticScholarRetriever
from app.shared.infra.search.retrievers.tavily import TavilyRetriever
from app.shared.infra.search.scraper.bs4_scraper import BS4Scraper
from app.shared.infra.search.scraper.pdf_scraper import PDFScraper

_RETRIEVER_TYPES: dict[str, type[BaseRetriever]] = {
    "local_rag": LocalRAGRetriever,
    "rag": LocalRAGRetriever,
    "duckduckgo": DuckDuckGoRetriever,
    "ddg": DuckDuckGoRetriever,
    "bing": BingRetriever,
    "bocha": BochaRetriever,
    "tavily": TavilyRetriever,
    "arxiv": ArxivRetriever,
    "semantic_scholar": SemanticScholarRetriever,
}


def get_retriever(
    name: str,
    *,
    subject: str | None = None,
    local_sections: list[object] | None = None,
) -> BaseRetriever:
    normalized = (name or "").strip().lower()
    retriever_type = _RETRIEVER_TYPES.get(normalized)
    if retriever_type is None:
        raise ValueError(f"Unknown retriever: {name}")
    if retriever_type is LocalRAGRetriever:
        return retriever_type(subject=subject, local_sections=local_sections)
    return retriever_type()


def get_configured_retriever_names(
    *,
    profile: str | None = None,
    include_local_rag: bool | None = None,
    include_fallback: bool = True,
) -> list[str]:
    settings = get_settings()
    configured = settings.parse_retrievers(
        profile=profile,
        include_local_rag=include_local_rag,
        include_fallback=include_fallback,
    )
    return [name for name in configured if name in _RETRIEVER_TYPES]


def get_external_retriever_names(*, profile: str | None = None) -> list[str]:
    return [
        name
        for name in get_configured_retriever_names(
            profile=profile,
            include_local_rag=False,
            include_fallback=True,
        )
        if name not in {"local_rag", "rag"}
    ]


def get_retrievers_for_subject(
    *,
    subject: str | None = None,
    local_sections: list[object] | None = None,
    profile: str | None = None,
    include_local_rag: bool | None = None,
    include_fallback: bool = True,
) -> list[BaseRetriever]:
    should_include_local_rag = include_local_rag
    if not (subject or local_sections):
        should_include_local_rag = False

    retrievers: list[BaseRetriever] = []
    for name in get_configured_retriever_names(
        profile=profile,
        include_local_rag=should_include_local_rag,
        include_fallback=include_fallback,
    ):
        try:
            retrievers.append(get_retriever(name, subject=subject, local_sections=local_sections))
        except ValueError:
            continue
    return retrievers


def get_scraper_for_url(url: str):
    normalized = (url or "").lower()
    if normalized.endswith(".pdf") or ".pdf?" in normalized:
        return PDFScraper()
    return BS4Scraper()


__all__ = [
    "get_configured_retriever_names",
    "get_external_retriever_names",
    "get_retriever",
    "get_retrievers_for_subject",
    "get_scraper_for_url",
]
