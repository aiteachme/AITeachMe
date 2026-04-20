"""OI Wiki site-specific retriever."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.retrievers.sites.duckduckgo_site import DuckDuckGoSiteRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SEARCH_ENDPOINT = "https://search.oi-wiki.org:8443/"
_REQUEST_HEADERS = {
    "User-Agent": "AITeachMe/0.2 (educational knowledge builder; https://github.com/)",
    "Accept": "application/json",
}


def _clean_highlight(values: object) -> str:
    if not isinstance(values, list):
        values = [values]
    text = " ".join(str(item or "") for item in values)
    text = text.replace("<em>", "").replace("</em>", "")
    text = _HTML_TAG_RE.sub("", text)
    return " ".join(text.split()).strip()


class OIWikiRetriever(DuckDuckGoSiteRetriever):
    """Search OI Wiki as a curated Chinese open educational source."""

    auto_register = True
    canonical_name = "oi_wiki"
    aliases = ("oiwiki", "oi-wiki")
    site_query_domain = "oi-wiki.org"
    allowed_domains = ("oi-wiki.org", "oi-wiki.com", "oiwiki.com", "oi.wiki")
    title_suffixes = (" - OI Wiki",)

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        count = clamp_max_results(max_results, upper=20)
        direct_results = await self._search_official_endpoint(normalized_query, max_results=count)
        if direct_results:
            return direct_results[:count]
        return await super().search(normalized_query, max_results=count)

    async def _search_official_endpoint(self, query: str, *, max_results: int) -> list[SearchResult]:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(
                timeout=settings.search.provider_timeout_s,
                follow_redirects=True,
                # OI Wiki's own search worker uses this public endpoint; some
                # Windows certificate stores reject its chain, so we do not send
                # secrets and keep this call isolated to read-only search.
                verify=False,
                headers=_REQUEST_HEADERS,
            ) as client:
                response = await client.get(_SEARCH_ENDPOINT, params={"s": query})
                response.raise_for_status()
                payload = response.json() or []
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("oi_wiki_search_endpoint_failed", query=query, error=str(exc))
            return []

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            url = urljoin("https://oi-wiki.org/", str(item.get("url") or "").strip())
            title = str(item.get("title") or "").strip()
            if not url or not title or url in seen_urls:
                continue
            seen_urls.add(url)
            result = make_search_result(
                url=url,
                title=title,
                snippet=_clean_highlight(item.get("highlight") or []),
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= max_results:
                break
        return results


__all__ = ["OIWikiRetriever"]
