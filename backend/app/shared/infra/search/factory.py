"""Factory helpers for the shared search stack.

- retrievers: find candidate sources/snippets
- readers: load content from a concrete URL (with legacy scraper aliases)
"""

from __future__ import annotations

import app.shared.infra.search.retrievers as _retriever_registry
import app.shared.infra.search.readers as _reader_registry

from app.shared.infra.config import get_settings
from app.shared.infra.search.retrievers import LocalRAGRetriever
from app.shared.infra.search.retrievers.base import BaseRetriever, get_registered_retriever_types
from app.shared.infra.search.readers import BS4Scraper
from app.shared.infra.search.readers.base import BaseReader, get_registered_reader_types


def get_retriever(
    name: str,
    *,
    subject: str | None = None,
    local_sections: list[object] | None = None,
) -> BaseRetriever:
    """Resolve one retriever by registered name."""

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
    """Return configured retriever names that are actually registered."""

    settings = get_settings()
    configured = settings.parse_retrievers(
        profile=profile,
        include_local_rag=include_local_rag,
        include_fallback=include_fallback,
    )
    registered_names = get_registered_retriever_types()
    return [name for name in configured if name in registered_names]


def get_external_retriever_names(*, profile: str | None = None) -> list[str]:
    """Return only external retrievers, excluding local knowledge retrieval."""

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
    """Build retriever instances for one subject / runtime context."""

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
    """Resolve the best URL reader.

    `reader` is the slightly broader internal term. Callers that think in
    scraping semantics can keep using `get_scraper_for_url`, which is an alias.
    """

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
    """Compatibility alias for callers that prefer the `scraper` term."""

    return get_reader_for_url(url, preferred=preferred)


__all__ = [
    "get_configured_retriever_names",
    "get_external_retriever_names",
    "get_reader_for_url",
    "get_retriever",
    "get_retrievers_for_subject",
    "get_scraper_for_url",
]



