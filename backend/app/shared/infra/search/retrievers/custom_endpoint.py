"""Custom HTTP endpoint retriever."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.settings import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class CustomEndpointRetriever(BaseRetriever):
    canonical_name = "custom_endpoint"
    aliases = ("custom", "custom_retriever")

    @classmethod
    def _endpoint(cls) -> str:
        return (get_env("CUSTOM_RETRIEVER_ENDPOINT") or get_env("RETRIEVER_ENDPOINT") or "").strip()

    @classmethod
    def is_available(cls) -> bool:
        return bool(cls._endpoint())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `CUSTOM_RETRIEVER_ENDPOINT`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        endpoint = self._endpoint()
        if not normalized_query or not endpoint:
            return []
        settings = get_settings()
        count = clamp_max_results(max_results, upper=50)
        query_param = (get_env("CUSTOM_RETRIEVER_QUERY_PARAM", "query") or "query").strip()
        max_param = (get_env("CUSTOM_RETRIEVER_MAX_RESULTS_PARAM", "max_results") or "max_results").strip()
        params = {
            query_param: normalized_query,
            max_param: count,
        }
        headers: dict[str, str] = {}
        api_key = (get_env("CUSTOM_RETRIEVER_API_KEY") or "").strip()
        if api_key:
            header_name = (get_env("CUSTOM_RETRIEVER_API_KEY_HEADER", "Authorization") or "Authorization").strip()
            header_value = api_key if header_name.lower() != "authorization" or api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
            headers[header_name] = header_value

        try:
            async with httpx.AsyncClient(timeout=settings.search.provider_timeout_s, follow_redirects=True) as client:
                response = await client.get(endpoint, params=params, headers=headers or None)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - custom provider behavior
            logger.warning("custom_endpoint_search_failed", endpoint=endpoint, error=str(exc), query=normalized_query)
            return []

        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover - custom provider behavior
            logger.warning("custom_endpoint_json_parse_failed", endpoint=endpoint, error=str(exc))
            return []
        return self._parse_payload(payload, count=count)

    def _parse_payload(self, payload: Any, *, count: int) -> list[SearchResult]:
        if isinstance(payload, dict):
            values = payload.get("results") or payload.get("items") or payload.get("data") or payload.get("documents") or []
        else:
            values = payload
        if not isinstance(values, list):
            return []

        results: list[SearchResult] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("href") or item.get("link")
            title = item.get("title") or item.get("name") or item.get("id") or url
            snippet = item.get("snippet") or item.get("body") or item.get("content") or item.get("raw_content") or item.get("text")
            result = make_search_result(url=url, title=title, snippet=snippet, source=self.name, snippet_limit=1600)
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["CustomEndpointRetriever"]
