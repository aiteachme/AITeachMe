"""SearXNG retriever for optional self-hosted / public metasearch instances."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class SearXngRetriever(BaseRetriever):
    aliases = ("searx",)

    @property
    def name(self) -> str:
        return "searxng"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        base_url = (get_env("SEARXNG_BASE_URL") or "").strip().rstrip("/")
        if not base_url:
            return []

        try:
            async with httpx.AsyncClient(timeout=settings.search_provider_timeout_s, follow_redirects=True) as client:
                response = await client.get(
                    f"{base_url}/search",
                    params={
                        "q": query,
                        "format": "json",
                        "language": "zh-CN",
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("searxng_search_failed", query=query, base_url=base_url, error=str(exc))
            return []

        values = (response.json() or {}).get("results") or []
        results: list[SearchResult] = []
        for item in values:
            url = str(item.get("url") or "").strip()
            title = " ".join(str(item.get("title") or "").split()).strip()
            snippet = " ".join(str(item.get("content") or "").split()).strip()
            if not url or not title:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source=self.name,
                )
            )
            if len(results) >= max_results:
                break
        return results


__all__ = ["SearXngRetriever"]

