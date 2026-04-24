"""Optional Bing retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env_choice
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class BingRetriever(BaseRetriever):
    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env_choice("BING_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `BING_API_KEY`"

    @property
    def name(self) -> str:
        return "bing"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env_choice("BING_API_KEY") or "").strip()
        if not api_key:
            return []
        count = clamp_max_results(max_results, upper=50)
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_PROVIDER_TIMEOUT_S) as client:
                response = await client.get(
                    "https://api.bing.microsoft.com/v7.0/search",
                    params={"q": normalized_query, "count": count},
                    headers={"Ocp-Apim-Subscription-Key": api_key},
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("bing_search_failed", error=str(exc), query=normalized_query)
            return []
        values = (response.json().get("webPages") or {}).get("value") or []
        results: list[SearchResult] = []
        for item in values:
            result = make_search_result(
                url=item.get("url"),
                title=item.get("name"),
                snippet=item.get("snippet"),
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["BingRetriever"]
