"""OpenRouter search retriever for Perplexity-style models."""

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


def _title_from_url(url: str, index: int) -> str:
    host = urlparse(str(url or "")).netloc.strip()
    return host or f"OpenRouter source {index}"


class OpenRouterSearchRetriever(BaseRetriever):
    canonical_name = "openrouter_search"
    aliases = ("openrouter",)

    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env_choice("OPENROUTER_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `OPENROUTER_API_KEY`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env_choice("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            return []
        count = clamp_max_results(max_results, upper=20)
        base_url = (get_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") or "https://openrouter.ai/api/v1").rstrip("/")
        payload = {
            "model": get_env("OPENROUTER_SEARCH_MODEL", "perplexity/sonar") or "perplexity/sonar",
            "messages": [
                {
                    "role": "system",
                    "content": "Return concise, source-grounded search findings with citations.",
                },
                {"role": "user", "content": normalized_query},
            ],
            "return_citations": True,
        }
        try:
            async with httpx.AsyncClient(timeout=max(DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, 20.0), follow_redirects=True) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": get_env("OPENROUTER_HTTP_REFERER", "http://localhost") or "http://localhost",
                        "X-Title": get_env("OPENROUTER_APP_TITLE", "AITeachMe") or "AITeachMe",
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("openrouter_search_failed", error=str(exc), query=normalized_query)
            return []

        data = response.json() or {}
        choice = (data.get("choices") or [{}])[0] or {}
        message = choice.get("message") or {}
        answer = clean_text(message.get("content") or "", limit=1000)
        citations = data.get("citations") or choice.get("citations") or message.get("citations") or []
        results = self._results_from_citations(citations, answer=answer, count=count)
        if results:
            return results
        return self._results_from_annotations(message.get("annotations") or [], answer=answer, count=count)

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

    def _results_from_annotations(self, values: list[object], *, answer: str, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for index, item in enumerate(values, 1):
            if not isinstance(item, dict):
                continue
            citation = item.get("url_citation") if item.get("type") == "url_citation" else item
            if not isinstance(citation, dict):
                continue
            url = citation.get("url")
            result = make_search_result(
                url=url,
                title=citation.get("title") or _title_from_url(str(url or ""), index),
                snippet=citation.get("content") or answer,
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["OpenRouterSearchRetriever"]
