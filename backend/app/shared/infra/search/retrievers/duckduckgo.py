"""DuckDuckGo retriever."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_DUCKDUCKGO_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
_DUCKDUCKGO_LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    )
}


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _resolve_result_url(raw_url: str) -> str:
    href = str(raw_url or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        href = f"https:{href}"
    elif href.startswith("/"):
        href = urljoin(_DUCKDUCKGO_HTML_ENDPOINT, href)

    parsed = urlparse(href)
    query_params = parse_qs(parsed.query)
    for key in ("uddg", "u"):
        values = query_params.get(key) or []
        if values and values[0].strip():
            return unquote(values[0].strip())
    return href


def _append_result(
    results: list[SearchResult],
    *,
    title: str,
    url: str,
    snippet: str,
    max_results: int,
    seen_urls: set[str],
) -> None:
    resolved_url = _resolve_result_url(url)
    cleaned_title = _clean_text(title)
    cleaned_snippet = _clean_text(snippet)
    if not resolved_url or not cleaned_title or resolved_url in seen_urls:
        return
    seen_urls.add(resolved_url)
    results.append(
        SearchResult(
            url=resolved_url,
            title=cleaned_title,
            snippet=cleaned_snippet,
            source="duckduckgo",
        )
    )
    if len(results) > max_results:
        del results[max_results:]


def _parse_duckduckgo_html_results(html: str, *, max_results: int) -> list[SearchResult]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - repo already depends on bs4 via readers
        return []

    soup = BeautifulSoup(html, "html.parser")
    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for container in soup.select("div.result"):
        link = container.select_one("a.result__a") or container.select_one("a.result-link")
        if link is None:
            continue
        snippet_node = container.select_one(".result__snippet") or container.select_one(".result-snippet")
        _append_result(
            results,
            title=link.get_text(" ", strip=True),
            url=link.get("href", ""),
            snippet=(snippet_node.get_text(" ", strip=True) if snippet_node is not None else ""),
            max_results=max_results,
            seen_urls=seen_urls,
        )
        if len(results) >= max_results:
            return results[:max_results]

    for link in soup.select("a.result-link"):
        row = link.find_parent("tr")
        snippet_node = None
        if row is not None:
            sibling = row.find_next_sibling("tr")
            if sibling is not None:
                snippet_node = sibling.select_one(".result-snippet")
        if snippet_node is None and row is not None:
            snippet_node = row.find_next("td", class_="result-snippet")
        _append_result(
            results,
            title=link.get_text(" ", strip=True),
            url=link.get("href", ""),
            snippet=(snippet_node.get_text(" ", strip=True) if snippet_node is not None else ""),
            max_results=max_results,
            seen_urls=seen_urls,
        )
        if len(results) >= max_results:
            return results[:max_results]

    return results[:max_results]


class DuckDuckGoRetriever(BaseRetriever):
    aliases = ("ddg",)

    @property
    def name(self) -> str:
        return "duckduckgo"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        try:
            from duckduckgo_search import AsyncDDGS
        except ImportError:
            logger.info("duckduckgo_package_missing_using_html_fallback")
        else:
            try:
                async with AsyncDDGS() as ddgs:
                    payload = await ddgs.atext(query, max_results=max_results)
                results = [
                    SearchResult(
                        url=str(item.get("href") or ""),
                        title=str(item.get("title") or ""),
                        snippet=str(item.get("body") or ""),
                        source=self.name,
                    )
                    for item in payload
                    if item.get("href")
                ]
                if results:
                    return results[:max_results]
            except Exception as exc:  # pragma: no cover - network/provider behavior
                logger.warning("duckduckgo_search_failed", error=str(exc), query=query)

        return await self._search_via_html(query, max_results=max_results)

    async def _search_via_html(self, query: str, *, max_results: int) -> list[SearchResult]:
        settings = get_settings()
        async with httpx.AsyncClient(
            timeout=settings.search_scrape_timeout_s,
            follow_redirects=True,
            headers=_REQUEST_HEADERS,
        ) as client:
            for endpoint in (_DUCKDUCKGO_HTML_ENDPOINT, _DUCKDUCKGO_LITE_ENDPOINT):
                try:
                    response = await client.get(endpoint, params={"q": query})
                    response.raise_for_status()
                except Exception as exc:  # pragma: no cover - network/provider behavior
                    logger.warning(
                        "duckduckgo_html_search_failed",
                        endpoint=endpoint,
                        error=str(exc),
                        query=query,
                    )
                    continue

                results = _parse_duckduckgo_html_results(response.text, max_results=max_results)
                if results:
                    logger.info(
                        "duckduckgo_html_fallback_succeeded",
                        endpoint=endpoint,
                        query=query,
                        result_count=len(results),
                    )
                    return results[:max_results]

        logger.warning("duckduckgo_unavailable", query=query)
        return []


__all__ = ["DuckDuckGoRetriever", "_parse_duckduckgo_html_results"]
