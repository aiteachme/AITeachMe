"""Plain text and markdown reader."""

from __future__ import annotations

import structlog

from app.shared.infra.search.readers.base import BaseReader
from app.shared.infra.search.readers.common import build_error_page, fetch_url, normalize_read_text
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)


class TextReader(BaseReader):
    canonical_name = "text"
    aliases = ("txt", "md", "markdown", "rst")
    priority = 80

    @classmethod
    def supports_url(cls, url: str) -> bool:
        normalized = str(url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        if normalized.endswith((".txt", ".text", ".md", ".markdown", ".rst")):
            return True
        return any(marker in normalized for marker in (".txt?", ".text?", ".md?", ".markdown?", ".rst?"))

    async def read(self, url: str) -> ScrapedPage:
        try:
            response = await fetch_url(url)
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("text_read_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="text/plain", reader_name=self.name)

        content_type = "text/markdown" if url.lower().endswith((".md", ".markdown", ".rst")) else "text/plain"
        return ScrapedPage(
            url=url,
            title="",
            content=normalize_read_text(response.text),
            content_type=content_type,
            reader_name=self.name,
        )


__all__ = ["TextReader"]
