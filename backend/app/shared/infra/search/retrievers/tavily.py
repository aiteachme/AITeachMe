"""Optional Tavily retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env, get_env_bool
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class TavilyRetriever(BaseRetriever):
    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env("TAVILY_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `TAVILY_API_KEY`"

    @property
    def name(self) -> str:
        return "tavily"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env("TAVILY_API_KEY") or "").strip()
        if not api_key:
            return []
        count = clamp_max_results(max_results, upper=20)

        payload = {
            "query": normalized_query,
            "search_depth": get_env("TAVILY_SEARCH_DEPTH", "basic") or "basic",
            "topic": get_env("TAVILY_TOPIC", "general") or "general",
            "include_answer": False,
            "include_raw_content": get_env_bool("TAVILY_INCLUDE_RAW_CONTENT", False),
            "include_images": False,
            "max_results": count,
        }
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_PROVIDER_TIMEOUT_S) as client:
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
            logger.warning("tavily_search_failed", error=str(exc), query=normalized_query)
            return []

        values = response.json().get("results") or []
        results: list[SearchResult] = []
        for item in values:
            result = make_search_result(
                url=item.get("url"),
                title=item.get("title"),
                snippet=item.get("raw_content") or item.get("content"),
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["TavilyRetriever"]
