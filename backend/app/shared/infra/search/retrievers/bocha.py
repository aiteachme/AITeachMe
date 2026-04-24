"""Bocha Web Search API retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env, get_env_choice
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, clean_text, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_BOCHA_SEARCH_ENDPOINT = "https://api.bochaai.com/v1/web-search"


class BochaRetriever(BaseRetriever):
    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env_choice("BOCHA_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `BOCHA_API_KEY`"

    @property
    def name(self) -> str:
        return "bocha"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env_choice("BOCHA_API_KEY") or "").strip()
        if not api_key:
            return []

        count = clamp_max_results(max_results, upper=50)
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, follow_redirects=True) as client:
                response = await client.post(
                    _BOCHA_SEARCH_ENDPOINT,
                    json={
                        "query": normalized_query,
                        "freshness": get_env("BOCHA_FRESHNESS", "noLimit") or "noLimit",
                        "summary": True,
                        "count": count,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("bocha_search_failed", error=str(exc), query=normalized_query)
            return []

        values = (((response.json() or {}).get("data") or {}).get("webPages") or {}).get("value") or []
        results: list[SearchResult] = []
        for item in values:
            snippet = clean_text(item.get("summary") or item.get("snippet") or "", limit=1000)
            site_name = clean_text(item.get("siteName"))
            date_published = clean_text(item.get("datePublished"))
            suffix = " ".join(part for part in [site_name, date_published] if part)
            if suffix:
                snippet = f"{snippet} [{suffix}]" if snippet else suffix
            result = make_search_result(
                url=item.get("url"),
                title=item.get("name") or item.get("title"),
                snippet=snippet,
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["BochaRetriever"]
