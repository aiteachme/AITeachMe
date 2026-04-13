"""HTML reader using httpx and BeautifulSoup when available."""

from __future__ import annotations

import re

import structlog

from app.shared.infra.search.readers.base import BaseReader
from app.shared.infra.search.readers.common import build_error_page, fetch_url, normalize_read_text
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)


class BS4Reader(BaseReader):
    canonical_name = "bs4"
    aliases = ("html", "web")
    priority = 10

    @classmethod
    def supports_url(cls, url: str) -> bool:
        normalized = str(url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        blocked_suffixes = (".pdf", ".docx", ".pptx", ".txt", ".text", ".md", ".markdown", ".rst")
        if normalized.endswith(blocked_suffixes):
            return False
        return not any(
            marker in normalized
            for marker in (".pdf?", ".docx?", ".pptx?", ".md?", ".markdown?", ".txt?", ".text?", ".rst?")
        )

    async def read(self, url: str) -> ScrapedPage:
        try:
            response = await fetch_url(url)
            html = response.text
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("bs4_read_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="text/html", reader_name=self.name)

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
            content=normalize_read_text(content),
            content_type="text/html",
            reader_name=self.name,
        )


__all__ = ["BS4Reader"]
