"""Web search dispatch helpers."""

from __future__ import annotations

import asyncio
import time

import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


async def _search_with_timeout(
    retriever,
    query: str,
    *,
    max_results: int,
    timeout_s: float,
) -> list[SearchResult]:
    try:
        return await asyncio.wait_for(
            retriever.traced_search(query, max_results=max_results),
            timeout=max(0.1, timeout_s),
        )
    except TimeoutError:
        logger.warning(
            "web_search_provider_timeout",
            provider=retriever.name,
            query=query,
            timeout_s=timeout_s,
        )
        return []
    except Exception as exc:
        logger.warning(
            "web_search_provider_failed",
            provider=retriever.name,
            query=query,
            error=str(exc),
        )
        return []


async def dispatch_web_search(
    query: str,
    *,
    top_k: int = 5,
    subject: str | None = None,
    local_sections: list[object] | None = None,
    profile: str | None = None,
    total_timeout_s: float | None = None,
    provider_timeout_s: float | None = None,
) -> list[SearchResult]:
    from app.shared.infra.search.factory import get_retrievers_for_subject

    settings = get_settings()
    total_budget = float(total_timeout_s or settings.search_total_timeout_s)
    provider_budget = float(provider_timeout_s or settings.search_provider_timeout_s)
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    started_at = time.monotonic()

    for retriever in get_retrievers_for_subject(
        subject=subject,
        local_sections=local_sections,
        profile=profile,
    ):
        elapsed = time.monotonic() - started_at
        remaining = total_budget - elapsed
        if remaining <= 0:
            logger.info("web_search_budget_exhausted", query=query, result_count=len(results))
            break

        provider_results = await _search_with_timeout(
            retriever,
            query,
            max_results=top_k,
            timeout_s=min(provider_budget, remaining),
        )
        for item in provider_results:
            if not item.url or item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            results.append(item)
            if len(results) >= top_k:
                logger.info(
                    "web_search_complete",
                    query=query,
                    provider=retriever.name,
                    result_count=len(results),
                    elapsed_ms=int((time.monotonic() - started_at) * 1000),
                )
                return results[:top_k]

    logger.info(
        "web_search_complete",
        query=query,
        result_count=len(results),
        elapsed_ms=int((time.monotonic() - started_at) * 1000),
    )
    return results[:top_k]


__all__ = ["dispatch_web_search"]
