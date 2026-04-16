"""Exa search retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_EXA_SEARCH_ENDPOINT = "https://api.exa.ai/search"


class ExaRetriever(BaseRetriever):
    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env("EXA_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `EXA_API_KEY`"

    @property
    def name(self) -> str:
        return "exa"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        api_key = (get_env("EXA_API_KEY") or "").strip()
        if not api_key:
            return []

        payload = {
            "query": query,
            "numResults": max_results,
            "contents": {"text": {"maxCharacters": 600}},
            "type": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=settings.search.provider_timeout_s, follow_redirects=True) as client:
                response = await client.post(
                    _EXA_SEARCH_ENDPOINT,
                    json=payload,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "x-api-key": api_key,
                    },
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("exa_search_failed", error=str(exc), query=query)
            return []

        values = (response.json() or {}).get("results") or []
        results: list[SearchResult] = []
        for item in values:
            url = str(item.get("url") or "").strip()
            title = " ".join(str(item.get("title") or "").split()).strip()
            snippet = self._build_snippet(item)
            if not url or not title:
                continue
            results.append(SearchResult(url=url, title=title, snippet=snippet, source=self.name))
            if len(results) >= max_results:
                break
        return results

    def _build_snippet(self, item: dict[str, object]) -> str:
        candidates = [
            item.get("text"),
            item.get("highlight"),
            item.get("summary"),
        ]
        contents = item.get("contents")
        if isinstance(contents, dict):
            text_payload = contents.get("text")
            if isinstance(text_payload, dict):
                candidates.append(text_payload.get("text"))
            elif isinstance(text_payload, str):
                candidates.append(text_payload)
        for candidate in candidates:
            text = " ".join(str(candidate or "").split()).strip()
            if text:
                return text[:600]
        return ""


__all__ = ["ExaRetriever"]
