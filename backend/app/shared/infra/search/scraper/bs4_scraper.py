"""HTML scraper using httpx and BeautifulSoup when available."""

from __future__ import annotations

import re

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.search.scraper.base import BaseScraper
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)


class BS4Scraper(BaseScraper):
    aliases = ("html", "web")
    priority = 10

    @property
    def name(self) -> str:
        return "bs4"

    @classmethod
    def supports_url(cls, url: str) -> bool:
        normalized = str(url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        return not (normalized.endswith(".pdf") or ".pdf?" in normalized)

    async def scrape(self, url: str) -> ScrapedPage:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=settings.search_scrape_timeout_s, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("bs4_scrape_failed", url=url, error=str(exc))
            return ScrapedPage(url=url, success=False, error=str(exc))

        title = ""
        content = ""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            content = soup.get_text("\n", strip=True)
        except Exception:
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = title_match.group(1).strip() if title_match else ""
            content = re.sub(r"<[^>]+>", " ", html)
            content = re.sub(r"\s+", " ", content).strip()
        return ScrapedPage(
            url=url,
            title=title,
            content=content[:12000],
            content_type="text/html",
            reader_name=self.name,
        )


__all__ = ["BS4Scraper"]
