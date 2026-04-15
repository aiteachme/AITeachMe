"""Baidu Baike site-specific retriever."""

from __future__ import annotations

import structlog

from app.shared.infra.search.retrievers.duckduckgo import DuckDuckGoRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class BaiduBaikeRetriever(DuckDuckGoRetriever):
    """Retrieves educational definitions constrained to Baidu Baike."""

    aliases = ("baike", "baidu_baike")

    @property
    def name(self) -> str:
        return "baidu_baike"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return []

        # Append site constraint to lock the search to Baidu Baike
        site_query = f"{normalized_query} site:baike.baidu.com"

        logger.info("baidu_baike_search_started", original_query=normalized_query)

        # Call the parent DuckDuckGo search logic with the constrained query
        results = await super().search(site_query, max_results=max_results)

        # Optional: Further post-process to strip Baidu Baike suffixes from titles for cleaner snippets
        cleaned_results: list[SearchResult] = []
        for item in results:
            clean_title = item.title.replace("_百度百科", "").replace(" - 百度百科", "").strip()
            item.title = clean_title
            item.source = self.name
            cleaned_results.append(item)

        return cleaned_results


__all__ = ["BaiduBaikeRetriever"]
