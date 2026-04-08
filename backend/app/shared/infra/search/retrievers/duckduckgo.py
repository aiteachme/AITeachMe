"""DuckDuckGo retriever."""

from __future__ import annotations

import structlog

from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class DuckDuckGoRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "duckduckgo"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        try:
            from duckduckgo_search import AsyncDDGS
        except ImportError:
            logger.warning("duckduckgo_unavailable")
            return []

        try:
            async with AsyncDDGS() as ddgs:
                payload = await ddgs.atext(query, max_results=max_results)
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("duckduckgo_search_failed", error=str(exc), query=query)
            return []

        return [
            SearchResult(
                url=str(item.get("href") or ""),
                title=str(item.get("title") or ""),
                snippet=str(item.get("body") or ""),
                source=self.name,
            )
            for item in payload
            if item.get("href")
        ]


__all__ = ["DuckDuckGoRetriever"]
