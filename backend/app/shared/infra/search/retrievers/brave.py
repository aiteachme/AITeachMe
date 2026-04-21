"""Brave Search API retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveRetriever(BaseRetriever):
    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env("BRAVE_SEARCH_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `BRAVE_SEARCH_API_KEY`"

    @property
    def name(self) -> str:
        return "brave"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env("BRAVE_SEARCH_API_KEY") or "").strip()
        if not api_key:
            return []
        count = clamp_max_results(max_results, upper=20)

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, follow_redirects=True) as client:
                response = await client.get(
                    _BRAVE_SEARCH_ENDPOINT,
                    params={"q": normalized_query, "count": count, "text_decorations": False, "spellcheck": False},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": api_key,
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("brave_search_failed", error=str(exc), query=normalized_query)
            return []

        values = ((response.json() or {}).get("web") or {}).get("results") or []
        results: list[SearchResult] = []
        for item in values:
            result = make_search_result(
                url=item.get("url"),
                title=item.get("title"),
                snippet=item.get("description") or item.get("snippet"),
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["BraveRetriever"]
