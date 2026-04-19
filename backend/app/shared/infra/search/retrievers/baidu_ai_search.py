"""Baidu Qianfan AI Search retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env, get_env_bool
from app.shared.infra.settings import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, clean_text, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_BAIDU_AI_SEARCH_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"


class BaiduAISearchRetriever(BaseRetriever):
    canonical_name = "baidu_ai_search"
    aliases = ("baidu_ai", "baidu_search")

    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env("BAIDU_AI_SEARCH_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `BAIDU_AI_SEARCH_API_KEY`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env("BAIDU_AI_SEARCH_API_KEY") or "").strip()
        if not api_key:
            return []
        settings = get_settings()
        count = clamp_max_results(max_results, upper=20)
        payload = {
            "messages": [{"role": "user", "content": normalized_query}],
            "model": get_env("BAIDU_AI_SEARCH_MODEL", "ernie-4.5-turbo-32k") or "ernie-4.5-turbo-32k",
            "search_source": get_env("BAIDU_AI_SEARCH_SOURCE", "baidu_search_v2") or "baidu_search_v2",
            "stream": False,
            "enable_deep_search": get_env_bool("BAIDU_AI_SEARCH_DEEP", False),
            "enable_corner_markers": True,
            "enable_followup_queries": False,
            "temperature": 0.11,
            "top_p": 0.55,
            "search_mode": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=max(settings.search.provider_timeout_s, 20.0)) as client:
                response = await client.post(
                    _BAIDU_AI_SEARCH_ENDPOINT,
                    json=payload,
                    headers={
                        "Authorization": api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("baidu_ai_search_failed", error=str(exc), query=normalized_query)
            return []

        data = response.json() or {}
        answer = clean_text(
            ((((data.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or ""),
            limit=1000,
        )
        values = data.get("references") or []
        results: list[SearchResult] = []
        for item in values:
            result = make_search_result(
                url=item.get("url"),
                title=item.get("title"),
                snippet=item.get("content") or answer,
                source=item.get("web_anchor") or self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["BaiduAISearchRetriever"]
