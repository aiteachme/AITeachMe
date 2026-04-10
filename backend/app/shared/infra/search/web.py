"""Web search dispatch helpers."""

from __future__ import annotations

import structlog

from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


async def dispatch_web_search(
    query: str,
    *,
    top_k: int = 5,
    subject: str | None = None,
    local_sections: list[object] | None = None,
) -> list[SearchResult]:
    from app.shared.infra.search.factory import get_retrievers_for_subject

    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for retriever in get_retrievers_for_subject(subject=subject, local_sections=local_sections):
        provider_results = await retriever.traced_search(query, max_results=top_k)
        for item in provider_results:
            if not item.url or item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            results.append(item)
            if len(results) >= top_k:
                logger.info("web_search_complete", query=query, provider=retriever.name, result_count=len(results))
                return results[:top_k]
    logger.info("web_search_complete", query=query, result_count=len(results))
    return results[:top_k]


__all__ = ["dispatch_web_search"]
