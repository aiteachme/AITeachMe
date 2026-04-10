"""Retriever and reader factory helpers."""

from __future__ import annotations

from app.shared.infra.config import get_settings
from app.shared.infra.search.retrievers import (
    ArxivRetriever,
    BingRetriever,
    BochaRetriever,
    DuckDuckGoRetriever,
    LocalRAGRetriever,
    SemanticScholarRetriever,
    TavilyRetriever,
)
from app.shared.infra.search.retrievers.base import BaseRetriever, get_registered_retriever_types
from app.shared.infra.search.scraper import BS4Scraper, PDFScraper
from app.shared.infra.search.scraper.base import BaseReader, get_registered_reader_types


def get_retriever(
    name: str,
    *,
    subject: str | None = None,
    local_sections: list[object] | None = None,
) -> BaseRetriever:
    normalized = (name or "").strip().lower()
    retriever_type = get_registered_retriever_types().get(normalized)
    if retriever_type is None:
        raise ValueError(f"Unknown retriever: {name}")
    if issubclass(retriever_type, LocalRAGRetriever):
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
    registered_names = get_registered_retriever_types()
    return [name for name in configured if name in registered_names]


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


def get_reader_for_url(url: str, *, preferred: str | None = None) -> BaseReader:
    registered = get_registered_reader_types()
    if preferred:
        reader_type = registered.get((preferred or "").strip().lower())
        if reader_type is None:
            raise ValueError(f"Unknown reader: {preferred}")
        return reader_type()

    unique_reader_types: list[type[BaseReader]] = []
    seen: set[type[BaseReader]] = set()
    for reader_type in registered.values():
        if reader_type in seen:
            continue
        seen.add(reader_type)
        unique_reader_types.append(reader_type)

    ranked: list[tuple[int, str, type[BaseReader]]] = []
    for reader_type in unique_reader_types:
        score = reader_type.match_priority(url)
        if score is None:
            continue
        ranked.append((score, reader_type.factory_names()[0], reader_type))

    if not ranked:
        return BS4Scraper()

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][2]()


def get_scraper_for_url(url: str, *, preferred: str | None = None) -> BaseReader:
    return get_reader_for_url(url, preferred=preferred)


__all__ = [
    "get_configured_retriever_names",
    "get_external_retriever_names",
    "get_reader_for_url",
    "get_retriever",
    "get_retrievers_for_subject",
    "get_scraper_for_url",
]
