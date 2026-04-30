"""Helpers for deciding whether local RAG results are enough."""

from __future__ import annotations

from collections.abc import Iterable

from app.shared.infra.search.types import SearchResult

DEFAULT_EFFECTIVE_LOCAL_SCORE = 0.55


def is_local_result(result: SearchResult) -> bool:
    url = str(result.url or "").strip().lower()
    source = str(result.source or "").strip().lower()
    return url.startswith("local://") or source == "local_rag"


def effective_local_result_count(
    results: Iterable[SearchResult],
    *,
    min_score: float = DEFAULT_EFFECTIVE_LOCAL_SCORE,
) -> int:
    threshold = max(0.0, float(min_score or 0.0))
    return sum(
        1
        for result in results
        if is_local_result(result) and max(0.0, float(result.score or 0.0)) >= threshold
    )


__all__ = [
    "DEFAULT_EFFECTIVE_LOCAL_SCORE",
    "effective_local_result_count",
    "is_local_result",
]
