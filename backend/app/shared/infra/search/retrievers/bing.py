"""Optional Bing retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class BingRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "bing"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        api_key = (get_env("BING_API_KEY") or "").strip()
        if not api_key:
            return []
        try:
            async with httpx.AsyncClient(timeout=settings.search_scrape_timeout_s) as client:
                response = await client.get(
                    "https://api.bing.microsoft.com/v7.0/search",
                    params={"q": query, "count": max_results},
                    headers={"Ocp-Apim-Subscription-Key": api_key},
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("bing_search_failed", error=str(exc), query=query)
            return []
        values = (response.json().get("webPages") or {}).get("value") or []
        return [
            SearchResult(
                url=str(item.get("url") or ""),
                title=str(item.get("name") or ""),
                snippet=str(item.get("snippet") or ""),
                source=self.name,
            )
            for item in values
            if item.get("url")
        ]


__all__ = ["BingRetriever"]
