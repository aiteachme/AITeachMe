"""MediaWiki site retriever base for curated wiki sources."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx
import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_REQUEST_HEADERS = {
    "User-Agent": "AITeachMe/0.2 (educational knowledge builder; https://github.com/)",
    "Accept": "application/json",
}


def _clean_snippet(value: object) -> str:
    text = _HTML_TAG_RE.sub("", str(value or ""))
    return " ".join(text.split()).strip()


def _page_url(*, page_base_url: str, title: str) -> str:
    normalized_title = str(title or "").strip().replace(" ", "_")
    if not normalized_title:
        return ""
    return f"{page_base_url.rstrip('/')}/{quote(normalized_title, safe='/:_')}"


class MediaWikiSiteRetriever(BaseRetriever):
    """Search one MediaWiki project through its official API."""

    auto_register = False
    cacheable = True
    api_url: str = ""
    page_base_url: str = ""
    site_label: str = ""
    namespace: int | None = 0

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query or not self.api_url or not self.page_base_url:
            return []
        count = clamp_max_results(max_results, upper=50)
        settings = get_settings()
        try:
            async with httpx.AsyncClient(
                timeout=settings.search.provider_timeout_s,
                follow_redirects=True,
                headers=_REQUEST_HEADERS,
            ) as client:
                response = await client.get(
                    self.api_url,
                    params=self._build_params(normalized_query, max_results=count),
                )
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("mediawiki_site_search_failed", retriever=self.name, query=normalized_query, error=str(exc))
            return []

        values = ((response.json() or {}).get("query") or {}).get("search") or []
        results: list[SearchResult] = []
        for item in values:
            title = " ".join(str(item.get("title") or "").split()).strip()
            url = _page_url(page_base_url=self.page_base_url, title=title)
            if not title or not url:
                continue
            snippet = _clean_snippet(item.get("snippet") or "")
            if self.site_label and snippet:
                snippet = f"{snippet} [{self.site_label}]"
            result = make_search_result(
                url=url,
                title=title,
                snippet=snippet,
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results

    def _build_params(self, query: str, *, max_results: int) -> dict[str, object]:
        params: dict[str, object] = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": max_results,
            "format": "json",
            "utf8": 1,
            "origin": "*",
        }
        if self.namespace is not None:
            params["srnamespace"] = int(self.namespace)
        return params


__all__ = ["MediaWikiSiteRetriever"]
