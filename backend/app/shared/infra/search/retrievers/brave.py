"""Brave Search API retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "brave"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        api_key = (get_env("BRAVE_SEARCH_API_KEY") or "").strip()
        if not api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=settings.search_provider_timeout_s, follow_redirects=True) as client:
                response = await client.get(
                    _BRAVE_SEARCH_ENDPOINT,
                    params={"q": query, "count": max_results, "text_decorations": False, "spellcheck": False},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": api_key,
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("brave_search_failed", error=str(exc), query=query)
            return []

        values = ((response.json() or {}).get("web") or {}).get("results") or []
        results: list[SearchResult] = []
        for item in values:
            url = str(item.get("url") or "").strip()
            title = " ".join(str(item.get("title") or "").split()).strip()
            snippet = " ".join(str(item.get("description") or item.get("snippet") or "").split()).strip()
            if not url or not title:
                continue
            results.append(SearchResult(url=url, title=title, snippet=snippet, source=self.name))
            if len(results) >= max_results:
                break
        return results


__all__ = ["BraveRetriever"]
