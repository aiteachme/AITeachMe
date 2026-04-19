"""SearchApi.io Google SERP retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.settings import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_SEARCHAPI_ENDPOINT = "https://www.searchapi.io/api/v1/search"


class SearchApiRetriever(BaseRetriever):
    canonical_name = "searchapi"
    aliases = ("searchapi_io",)

    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env("SEARCHAPI_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `SEARCHAPI_API_KEY`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env("SEARCHAPI_API_KEY") or "").strip()
        if not api_key:
            return []
        settings = get_settings()
        count = clamp_max_results(max_results, upper=20)
        params = {
            "q": normalized_query,
            "engine": get_env("SEARCHAPI_ENGINE", "google") or "google",
        }
        for env_name, param_name in (("SEARCHAPI_GL", "gl"), ("SEARCHAPI_HL", "hl")):
            value = (get_env(env_name) or "").strip()
            if value:
                params[param_name] = value

        try:
            async with httpx.AsyncClient(timeout=settings.search.provider_timeout_s, follow_redirects=True) as client:
                response = await client.get(
                    _SEARCHAPI_ENDPOINT,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "X-SearchApi-Source": "AITeachMe",
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("searchapi_search_failed", error=str(exc), query=normalized_query)
            return []

        values = (response.json() or {}).get("organic_results") or []
        results: list[SearchResult] = []
        for item in values:
            url = str(item.get("link") or item.get("url") or "").strip()
            if "youtube.com" in url:
                continue
            result = make_search_result(
                url=url,
                title=item.get("title"),
                snippet=item.get("snippet") or item.get("description"),
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["SearchApiRetriever"]
