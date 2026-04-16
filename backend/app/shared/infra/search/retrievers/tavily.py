"""Optional Tavily retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env, get_env_bool
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
            "search_depth": get_env("TAVILY_SEARCH_DEPTH", "basic") or "basic",
            "topic": get_env("TAVILY_TOPIC", "general") or "general",
            "include_answer": False,
            "include_raw_content": get_env_bool("TAVILY_INCLUDE_RAW_CONTENT", False),
            "include_images": False,
            "max_results": max_results,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.search.provider_timeout_s) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("tavily_search_failed", error=str(exc), query=query)
            return []

        values = response.json().get("results") or []
        return [
            SearchResult(
                url=str(item.get("url") or ""),
                title=str(item.get("title") or ""),
                snippet=str(item.get("raw_content") or item.get("content") or "")[:1000],
                source=self.name,
            )
            for item in values
            if item.get("url")
        ]


__all__ = ["TavilyRetriever"]

