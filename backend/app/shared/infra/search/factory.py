"""Registry-backed factory helpers for the shared search stack.

The search layer has two plugin-like families:

- retrievers find candidate sources/snippets from local RAG or external search
- readers load content from a concrete URL returned by a retriever

Importing ``app.shared.infra.search.retrievers`` and ``.readers`` at module load
time is intentional: those packages auto-register their subclasses through
``BaseRetriever.__init_subclass__`` and ``BaseReader.__init_subclass__``.
"""

from __future__ import annotations

import app.shared.infra.search.readers as _reader_registry
import app.shared.infra.search.retrievers as _retriever_registry

from app.shared.infra.settings import get_settings
from app.shared.infra.search.readers import BS4Reader
from app.shared.infra.search.readers.base import BaseReader, get_registered_reader_types
from app.shared.infra.search.retrievers import LocalRAGRetriever
from app.shared.infra.search.retrievers.base import BaseRetriever, get_registered_retriever_types


def get_retriever(
    name: str,
    *,
    course_id: str | None = None,
    local_sections: list[object] | None = None,
) -> BaseRetriever:
    """Resolve one retriever by registered name.

    Local RAG retrievers need runtime context (course id / in-memory sections),
    while external retrievers are stateless wrappers around provider APIs.
    """

    normalized = (name or "").strip().lower()
    retriever_type = get_registered_retriever_types().get(normalized)
    if retriever_type is None:
        raise ValueError(f"Unknown retriever: {name}")
    if not retriever_type.is_available():
        reason = retriever_type.availability_reason() or "retriever is unavailable"
        raise ValueError(f"Retriever `{normalized}` is unavailable: {reason}")
    if issubclass(retriever_type, LocalRAGRetriever):
        return retriever_type(course_id=course_id, local_sections=local_sections)
    return retriever_type()


def get_available_retriever_names(names: list[str]) -> list[str]:
    """Filter configured names down to registered and currently available retrievers.

    Availability usually means the required API key or base URL is configured.
    Missing optional providers are silently skipped so broad default profiles can
    include many providers without requiring every user to configure every key.
    """

    available: list[str] = []
    registered = get_registered_retriever_types()
    for name in names:
        retriever_type = registered.get((name or "").strip().lower())
        if retriever_type is None:
            continue
        if not retriever_type.is_available():
            continue
        available.append(name)
    return available


def get_configured_retriever_names(
    *,
    profile: str | None = None,
    include_local_rag: bool | None = None,
    include_external: bool = True,
    include_fallback: bool = True,
) -> list[str]:
    """Return configured retriever names that are registered and available.

    The raw configured list comes from ``settings.parse_retrievers``. This helper
    then removes names whose classes are not registered and providers that are
    not available in the current runtime.
    """

    settings = get_settings()
    configured = settings.parse_retrievers(
        profile=profile,
        include_local_rag=include_local_rag,
        include_external=include_external,
        include_fallback=include_fallback,
    )
    registered_names = get_registered_retriever_types()
    candidate_names = [name for name in configured if name in registered_names]
    return get_available_retriever_names(candidate_names)


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


def get_retrievers_for_course(
    *,
    course_id: str | None = None,
    local_sections: list[object] | None = None,
    profile: str | None = None,
    include_local_rag: bool | None = None,
    include_external: bool = True,
    include_fallback: bool = True,
) -> list[BaseRetriever]:
    """Build retriever instances for one course id / runtime context.

    If neither ``course_id`` nor ``local_sections`` is provided, ``local_rag`` is
    disabled even when the profile includes it. That avoids a confusing
    no-context local search attempt from generic web search tools.
    """

    should_include_local_rag = include_local_rag
    if not (course_id or local_sections):
        should_include_local_rag = False

    retrievers: list[BaseRetriever] = []
    for name in get_configured_retriever_names(
        profile=profile,
        include_local_rag=should_include_local_rag,
        include_external=include_external,
        include_fallback=include_fallback,
    ):
        try:
            retrievers.append(get_retriever(name, course_id=course_id, local_sections=local_sections))
        except ValueError:
            continue
    return retrievers


def get_reader_for_url(url: str, *, preferred: str | None = None) -> BaseReader:
    """Resolve the best URL reader.

    Readers declare URL match priority. Explicit ``preferred`` names are honored
    first; otherwise the highest-priority compatible reader wins, with BS4 HTML
    reading as the generic fallback.
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
        return BS4Reader()

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][2]()


__all__ = [
    "get_available_retriever_names",
    "get_configured_retriever_names",
    "get_external_retriever_names",
    "get_reader_for_url",
    "get_retriever",
    "get_retrievers_for_course",
]
