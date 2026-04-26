"""Jina Search API retriever."""

from __future__ import annotations

from urllib.parse import quote

import httpx
import structlog

from app.shared.infra.env_support import get_env_bool, get_env_choice
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_JINA_SEARCH_ENDPOINT = "https://s.jina.ai"


class JinaSearchRetriever(BaseRetriever):
    canonical_name = "jina_search"
    aliases = ("jina",)

    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env_choice("JINA_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `JINA_API_KEY`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env_choice("JINA_API_KEY") or "").strip()
        if not api_key:
            return []
        count = clamp_max_results(max_results, upper=20)
        enrich = get_env_bool("JINA_SEARCH_ENRICH", False)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if enrich:
            headers["X-Engine"] = "direct"
            headers["X-With-Images-Summary"] = "true"
        else:
            headers["X-Respond-With"] = "no-content"

        try:
            async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, follow_redirects=True) as client:
                response = await client.get(f"{_JINA_SEARCH_ENDPOINT}/{quote(normalized_query)}", headers=headers)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("jina_search_failed", error=str(exc), query=normalized_query)
            return []

        values = (response.json() or {}).get("data") or []
        results: list[SearchResult] = []
        for item in values:
            result = make_search_result(
                url=item.get("url"),
                title=item.get("title"),
                snippet=item.get("content") or item.get("description"),
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["JinaSearchRetriever"]
