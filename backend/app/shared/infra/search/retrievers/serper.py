"""Serper Google SERP retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.env_support import get_env, get_env_bool, get_env_choice
from app.shared.infra.search.defaults import DEFAULT_SEARCH_PROVIDER_TIMEOUT_S
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, clean_text, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_SERPER_BASE_URL = "https://google.serper.dev"


class SerperRetriever(BaseRetriever):
    canonical_name = "serper"
    aliases = ("serper_scholar", "google_serp", "google_scholar")

    @classmethod
    def is_available(cls) -> bool:
        return bool((get_env_choice("SERPER_API_KEY") or "").strip())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `SERPER_API_KEY`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        api_key = (get_env_choice("SERPER_API_KEY") or "").strip()
        if not api_key:
            return []
        count = clamp_max_results(max_results, upper=20)
        mode = (get_env("SERPER_SEARCH_MODE", "search") or "search").strip().lower()
        if mode not in {"search", "scholar"}:
            mode = "search"
        payload = {
            "q": normalized_query,
            "num": count,
            "gl": get_env("SERPER_GL", "us") or "us",
            "hl": get_env("SERPER_HL", "en") or "en",
            "autocorrect": get_env_bool("SERPER_AUTOCORRECT", True),
        }
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_SEARCH_PROVIDER_TIMEOUT_S, follow_redirects=True) as client:
                response = await client.post(
                    f"{_SERPER_BASE_URL}/{mode}",
                    json=payload,
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("serper_search_failed", error=str(exc), query=normalized_query, mode=mode)
            return []

        data = response.json() or {}
        values = data.get("organic") or []
        results: list[SearchResult] = []
        for item in values:
            snippet = item.get("snippet") or item.get("description")
            if mode == "scholar":
                details = [
                    item.get("publicationInfo"),
                    f"year: {item.get('year')}" if item.get("year") else "",
                    f"cited by: {item.get('citedBy')}" if item.get("citedBy") is not None else "",
                    item.get("pdfUrl"),
                ]
                snippet = " | ".join(part for part in [snippet, *details] if part)
            result = make_search_result(
                url=item.get("link") or item.get("url") or item.get("pdfUrl"),
                title=item.get("title"),
                snippet=snippet,
                source=f"{self.name}_{mode}" if mode == "scholar" else self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        if results:
            return results
        return self._answer_box_result(data, normalized_query)

    def _answer_box_result(self, data: dict[str, object], query: str) -> list[SearchResult]:
        answer_box = data.get("answerBox")
        if isinstance(answer_box, dict):
            result = make_search_result(
                url=answer_box.get("link") or answer_box.get("url"),
                title=answer_box.get("title") or query,
                snippet=answer_box.get("answer") or answer_box.get("snippet"),
                source=self.name,
            )
            return [result] if result is not None else []
        knowledge_graph = data.get("knowledgeGraph")
        if isinstance(knowledge_graph, dict):
            result = make_search_result(
                url=knowledge_graph.get("website") or knowledge_graph.get("url"),
                title=knowledge_graph.get("title") or query,
                snippet=clean_text(knowledge_graph.get("description")),
                source=self.name,
            )
            return [result] if result is not None else []
        return []


__all__ = ["SerperRetriever"]
