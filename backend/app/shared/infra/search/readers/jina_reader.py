"""Optional Jina Reader adapter.

Jina Reader is useful as a fallback for pages that are hard to scrape with a
basic HTML parser. It is opt-in because it sends URLs to an external service.
Set ``JINA_READER_ENABLED=true`` to make it participate in automatic reader
selection, or request it explicitly via ``preferred="jina"``.
"""

from __future__ import annotations

from urllib.parse import quote

import structlog

from app.shared.infra.env_support import get_env_bool, get_env_choice
from app.shared.infra.search.readers.base import BaseReader
from app.shared.infra.search.readers.common import build_error_page, fetch_url, normalize_read_text
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)


class JinaReader(BaseReader):
    canonical_name = "jina"
    aliases = ("jina_reader", "reader")
    priority = 20

    @classmethod
    def supports_url(cls, url: str) -> bool:
        if not get_env_bool("JINA_READER_ENABLED", False):
            return False
        normalized = str(url or "").strip().lower()
        return normalized.startswith(("http://", "https://"))

    @staticmethod
    def reader_url(url: str) -> str:
        normalized = str(url or "").strip()
        return f"https://r.jina.ai/{quote(normalized, safe=':/?&=%#')}"

    async def read(self, url: str) -> ScrapedPage:
        reader_url = self.reader_url(url)
        headers = {}
        api_key = (get_env_choice("JINA_API_KEY") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = await fetch_url(reader_url, headers=headers or None)
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("jina_reader_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type="text/markdown", reader_name=self.name)

        content = normalize_read_text(response.text)
        title = ""
        if content.startswith("Title:"):
            first_line, _, rest = content.partition("\n")
            title = first_line.removeprefix("Title:").strip()
            content = rest.strip() or content
        return ScrapedPage(
            url=url,
            title=title,
            content=content,
            content_type="text/markdown",
            reader_name=self.name,
        )


__all__ = ["JinaReader"]
