"""Google Custom Search JSON API retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_GOOGLE_CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


class GoogleCSERetriever(BaseRetriever):
    canonical_name = "google_cse"
    aliases = ("google", "google_custom_search")

    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env("GOOGLE_API_KEY") or "").strip() and (get_env("GOOGLE_CX_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `GOOGLE_API_KEY` or `GOOGLE_CX_KEY`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env("GOOGLE_API_KEY") or "").strip()
        cx_key = (get_env("GOOGLE_CX_KEY") or "").strip()
        if not api_key or not cx_key:
            return []
        count = clamp_max_results(max_results, upper=10)
        params = {
            "key": api_key,
            "cx": cx_key,
            "q": normalized_query,
            "num": count,
        }
        safe = (get_env("GOOGLE_SAFE_SEARCH") or "").strip()
        if safe:
            params["safe"] = safe
        language_restrict = (get_env("GOOGLE_LR") or "").strip()
        if language_restrict:
            params["lr"] = language_restrict

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, follow_redirects=True) as client:
                response = await client.get(_GOOGLE_CSE_ENDPOINT, params=params)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("google_cse_search_failed", error=str(exc), query=normalized_query)
            return []

        values = (response.json() or {}).get("items") or []
        results: list[SearchResult] = []
        for item in values:
            url = str(item.get("link") or "").strip()
            if "youtube.com" in url:
                continue
            result = make_search_result(
                url=url,
                title=item.get("title"),
                snippet=item.get("snippet") or item.get("htmlSnippet"),
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["GoogleCSERetriever"]
