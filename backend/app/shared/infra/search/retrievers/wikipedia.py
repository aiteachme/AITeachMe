"""Wikipedia retriever backed by the official MediaWiki search API."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WIKIPEDIA_API_TEMPLATE = "https://{lang}.wikipedia.org/w/api.php"
_REQUEST_HEADERS = {
    "User-Agent": "AITeachMe/0.2 (educational knowledge builder; https://github.com/)",
    "Accept": "application/json",
}


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def _clean_snippet(value: str) -> str:
    text = _HTML_TAG_RE.sub("", str(value or ""))
    return " ".join(text.split()).strip()


def _result_url(*, lang: str, title: str) -> str:
    normalized_title = str(title or "").strip().replace(" ", "_")
    if not normalized_title:
        return ""
    return f"https://{lang}.wikipedia.org/wiki/{quote(normalized_title)}"


class WikipediaRetriever(BaseRetriever):
    aliases = ("wiki",)

    @property
    def name(self) -> str:
        return "wikipedia"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return []

        languages = ["zh", "en"] if _contains_cjk(normalized_query) else ["en", "zh"]
        settings = get_settings()
        seen_urls: set[str] = set()
        results: list[SearchResult] = []

        async with httpx.AsyncClient(
            timeout=settings.search_scrape_timeout_s,
            follow_redirects=True,
            headers=_REQUEST_HEADERS,
        ) as client:
            for lang in languages:
                payload = await self._search_language(
                    client,
                    query=normalized_query,
                    lang=lang,
                    max_results=max_results,
                )
                for item in payload:
                    if item.url in seen_urls:
                        continue
                    seen_urls.add(item.url)
                    results.append(item)
                    if len(results) >= max_results:
                        return results[:max_results]
        return results[:max_results]

    async def _search_language(
        self,
        client: httpx.AsyncClient,
        *,
        query: str,
        lang: str,
        max_results: int,
    ) -> list[SearchResult]:
        try:
            response = await client.get(
                _WIKIPEDIA_API_TEMPLATE.format(lang=lang),
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": max_results,
                    "format": "json",
                    "utf8": 1,
                    "origin": "*",
                },
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("wikipedia_search_failed", lang=lang, query=query, error=str(exc))
            return []

        values = ((response.json() or {}).get("query") or {}).get("search") or []
        results: list[SearchResult] = []
        for item in values:
            title = " ".join(str(item.get("title") or "").split()).strip()
            url = _result_url(lang=lang, title=title)
            if not url or not title:
                continue
            snippet = _clean_snippet(item.get("snippet") or "")
            if lang == "en" and snippet:
                snippet = f"{snippet} [Wikipedia EN]"
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source=self.name,
                )
            )
        return results


__all__ = ["WikipediaRetriever"]
