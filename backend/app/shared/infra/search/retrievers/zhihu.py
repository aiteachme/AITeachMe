"""Zhihu site-specific retriever."""

from __future__ import annotations

import structlog

from app.shared.infra.search.retrievers.duckduckgo import DuckDuckGoRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class ZhihuRetriever(DuckDuckGoRetriever):
    """Retrieves discussions and answers constrained to Zhihu."""

    aliases = ("zhihu",)

    @property
    def name(self) -> str:
        return "zhihu"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return []

        # Append site constraint to lock the search to Zhihu
        site_query = f"{normalized_query} site:zhihu.com"

        logger.info("zhihu_search_started", original_query=normalized_query)

        # Call the parent DuckDuckGo search logic with the constrained query
        results = await super().search(site_query, max_results=max_results)

        # Post-process to remove common suffixes
        for item in results:
            item.title = item.title.replace(" - 知乎", "").strip()
            item.source = self.name

        return results


__all__ = ["ZhihuRetriever"]
