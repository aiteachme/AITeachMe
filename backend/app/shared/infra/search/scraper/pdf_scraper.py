"""PDF scraper using PyMuPDF when available."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.search.scraper.base import BaseScraper
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)


class PDFScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "pdf"

    async def scrape(self, url: str) -> ScrapedPage:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(timeout=settings.search_scrape_timeout_s, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.content
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("pdf_scrape_failed", url=url, error=str(exc))
            return ScrapedPage(url=url, success=False, error=str(exc), content_type="application/pdf")

        try:
            import fitz

            document = fitz.open(stream=payload, filetype="pdf")
            pages = [page.get_text("text") for page in document]
            content = "\n\n".join(text.strip() for text in pages if text.strip())
            title = document.metadata.get("title") or ""
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("pdf_parse_failed", url=url, error=str(exc))
            return ScrapedPage(url=url, success=False, error=str(exc), content_type="application/pdf")
        return ScrapedPage(url=url, title=title, content=content[:12000], content_type="application/pdf")


__all__ = ["PDFScraper"]
