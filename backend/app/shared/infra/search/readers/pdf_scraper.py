"""PDF reader using PyMuPDF when available."""

from __future__ import annotations
import structlog

from app.shared.infra.search.readers.base import BaseScraper
from app.shared.infra.search.readers.common import build_error_page, fetch_url, normalize_scraped_text
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)


class PDFScraper(BaseScraper):
    priority = 100

    @property
    def name(self) -> str:
        return "pdf"

    @classmethod
    def supports_url(cls, url: str) -> bool:
        normalized = str(url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        return normalized.endswith(".pdf") or ".pdf?" in normalized

    async def scrape(self, url: str) -> ScrapedPage:
        try:
            response = await fetch_url(url)
            payload = response.content
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("pdf_scrape_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="application/pdf", reader_name=self.name)

        try:
            import fitz

            document = fitz.open(stream=payload, filetype="pdf")
            pages = [page.get_text("text") for page in document]
            content = "\n\n".join(text.strip() for text in pages if text.strip())
            title = document.metadata.get("title") or ""
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("pdf_parse_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="application/pdf", reader_name=self.name)
        return ScrapedPage(
            url=url,
            title=title,
            content=normalize_scraped_text(content),
            content_type="application/pdf",
            reader_name=self.name,
        )


__all__ = ["PDFScraper"]



