"""Optional Tavily retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class TavilyRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "tavily"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        api_key = (get_env("TAVILY_API_KEY") or "").strip()
        if not api_key:
            return []

        payload = {
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "max_results": max_results,
            "api_key": api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.search_scrape_timeout_s) as client:
                response = await client.post("https://api.tavily.com/search", json=payload)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("tavily_search_failed", error=str(exc), query=query)
            return []

        values = response.json().get("results") or []
        return [
            SearchResult(
                url=str(item.get("url") or ""),
                title=str(item.get("title") or ""),
                snippet=str(item.get("content") or ""),
                source=self.name,
            )
            for item in values
            if item.get("url")
        ]


__all__ = ["TavilyRetriever"]
