"""PDF reader using pdfplumber when available."""

from __future__ import annotations

from io import BytesIO

import structlog

from app.shared.infra.env_support import get_env_bool
from app.shared.infra.search.readers.base import BaseReader
from app.shared.infra.search.readers.common import build_error_page, fetch_url, normalize_read_text
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)


class PDFReader(BaseReader):
    canonical_name = "pdf"
    priority = 100

    @classmethod
    def supports_url(cls, url: str) -> bool:
        if not get_env_bool("AITEACHME_ENABLE_BUILTIN_PDF", True):
            return False
        normalized = str(url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        return normalized.endswith(".pdf") or ".pdf?" in normalized

    async def read(self, url: str) -> ScrapedPage:
        try:
            response = await fetch_url(url)
            payload = response.content
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("pdf_read_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="application/pdf", reader_name=self.name)

        try:
            import pdfplumber

            with pdfplumber.open(BytesIO(payload)) as document:
                pages = [page.extract_text() or "" for page in document.pages]
                content = "\n\n".join(text.strip() for text in pages if text.strip())
                metadata = document.metadata or {}
                title = metadata.get("Title") or metadata.get("title") or ""
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("pdf_parse_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="application/pdf", reader_name=self.name)
        return ScrapedPage(
            url=url,
            title=title,
            content=normalize_read_text(content),
            content_type="application/pdf",
            reader_name=self.name,
        )


__all__ = ["PDFReader"]
