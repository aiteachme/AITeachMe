"""Perplexity Sonar search retriever."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
import structlog

from app.shared.infra.env_support import get_env, get_env_choice
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, clean_text, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_PERPLEXITY_ENDPOINT = "https://api.perplexity.ai/chat/completions"


def _title_from_url(url: str, index: int) -> str:
    host = urlparse(str(url or "")).netloc.strip()
    return host or f"Perplexity source {index}"


class PerplexityRetriever(BaseRetriever):
    canonical_name = "perplexity"

    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env_choice("PERPLEXITY_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `PERPLEXITY_API_KEY`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env_choice("PERPLEXITY_API_KEY") or "").strip()
        if not api_key:
            return []
        count = clamp_max_results(max_results, upper=20)
        model = (get_env("PERPLEXITY_SEARCH_MODEL", "sonar") or "sonar").strip()
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return concise, source-grounded search findings with citations.",
                },
                {"role": "user", "content": normalized_query},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=max(DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, 20.0)) as client:
                response = await client.post(
                    _PERPLEXITY_ENDPOINT,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("perplexity_search_failed", error=str(exc), query=normalized_query)
            return []

        data = response.json() or {}
        answer = clean_text(
            ((((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or ""),
            limit=1000,
        )
        results = self._results_from_search_results(data.get("search_results") or [], answer=answer, count=count)
        if results:
            return results
        return self._results_from_citations(data.get("citations") or [], answer=answer, count=count)

    def _results_from_search_results(self, values: list[object], *, answer: str, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for index, item in enumerate(values, 1):
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            title = item.get("title") or _title_from_url(str(url or ""), index)
            snippet = item.get("snippet") or item.get("content") or item.get("date") or answer
            result = make_search_result(url=url, title=title, snippet=snippet, source=self.name)
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results

    def _results_from_citations(self, values: list[object], *, answer: str, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for index, value in enumerate(values, 1):
            url = value.get("url") if isinstance(value, dict) else value
            title = value.get("title") if isinstance(value, dict) else None
            result = make_search_result(
                url=url,
                title=title or _title_from_url(str(url or ""), index),
                snippet=answer,
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["PerplexityRetriever"]
