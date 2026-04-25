"""MediaWiki page reader using official API extracts."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

import httpx
import structlog

from app.shared.infra.search.defaults import DEFAULT_SEARCH_SCRAPE_TIMEOUT_S
from app.shared.infra.search.readers.base import BaseReader
from app.shared.infra.search.readers.common import DEFAULT_READER_HEADERS, build_error_page, normalize_read_text
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)

_MEDIAWIKI_DOMAINS: dict[str, str] = {
    "zh.wikipedia.org": "https://zh.wikipedia.org/w/api.php",
    "zh.wikibooks.org": "https://zh.wikibooks.org/w/api.php",
    "zh.wikiversity.org": "https://zh.wikiversity.org/w/api.php",
    "zh.wiktionary.org": "https://zh.wiktionary.org/w/api.php",
}


def _normalize_domain(url: str) -> str:
    domain = urlparse(str(url or "")).netloc.lower().strip()
    if domain.startswith("www."):
        return domain[4:]
    return domain


def _page_title_from_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    path = unquote(parsed.path or "")
    marker = "/wiki/"
    if marker not in path:
        return ""
    title = path.split(marker, 1)[1].split("#", 1)[0].strip()
    return title.replace("_", " ").strip()


class MediaWikiReader(BaseReader):
    """Read Chinese MediaWiki pages through the action API instead of scraping HTML."""

    canonical_name = "mediawiki"
    aliases = ("wiki_api", "wikimedia")
    priority = 30

    @classmethod
    def supports_url(cls, url: str) -> bool:
        domain = _normalize_domain(url)
        return domain in _MEDIAWIKI_DOMAINS and bool(_page_title_from_url(url))

    async def read(self, url: str) -> ScrapedPage:
        domain = _normalize_domain(url)
        api_url = _MEDIAWIKI_DOMAINS.get(domain)
        title = _page_title_from_url(url)
        if not api_url or not title:
            return build_error_page(url, error="unsupported MediaWiki URL", content_type="application/json", reader_name=self.name)

        try:
            async with httpx.AsyncClient(
                timeout=DEFAULT_SEARCH_SCRAPE_TIMEOUT_S,
                follow_redirects=True,
                headers={**DEFAULT_READER_HEADERS, "Accept": "application/json"},
            ) as client:
                response = await client.get(
                    api_url,
                    params={
                        "action": "query",
                        "prop": "extracts",
                        "explaintext": 1,
                        "exsectionformat": "plain",
                        "redirects": 1,
                        "titles": title,
                        "format": "json",
                        "utf8": 1,
                        "origin": "*",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.info("mediawiki_read_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="application/json", reader_name=self.name)

        pages = ((payload or {}).get("query") or {}).get("pages") or {}
        page = next((item for item in pages.values() if isinstance(item, dict)), {})
        if not page or "missing" in page or "invalid" in page:
            return ScrapedPage(
                url=url,
                title=title,
                success=False,
                error="MediaWiki page missing or invalid",
                content_type="application/json",
                reader_name=self.name,
            )

        page_title = str(page.get("title") or title).strip()
        content = normalize_read_text(str(page.get("extract") or ""))
        if not content:
            return ScrapedPage(
                url=url,
                title=page_title,
                success=False,
                error="MediaWiki extract is empty",
                content_type="application/json",
                reader_name=self.name,
            )
        return ScrapedPage(
            url=url,
            title=page_title,
            content=content,
            content_type="application/json",
            reader_name=self.name,
        )


__all__ = ["MediaWikiReader"]
