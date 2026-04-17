"""Small helpers shared by search retrievers."""

from __future__ import annotations

from typing import Any

from app.shared.infra.search.types import SearchResult


def normalize_query(query: str) -> str:
    return " ".join(str(query or "").split()).strip()


def clamp_max_results(value: int, *, default: int = 5, upper: int = 20) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(upper, parsed))


def clean_text(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if limit is not None and len(text) > limit:
        return text[: max(1, limit - 1)].rstrip() + "…"
    return text


def make_search_result(
    *,
    url: Any,
    title: Any,
    snippet: Any = "",
    source: str,
    score: float = 0.0,
    snippet_limit: int | None = 1000,
) -> SearchResult | None:
    normalized_url = clean_text(url)
    normalized_title = clean_text(title)
    if not normalized_url or not normalized_title:
        return None
    return SearchResult(
        url=normalized_url,
        title=normalized_title,
        snippet=clean_text(snippet, limit=snippet_limit),
        score=float(score or 0.0),
        source=source,
    )


__all__ = [
    "clamp_max_results",
    "clean_text",
    "make_search_result",
    "normalize_query",
]
