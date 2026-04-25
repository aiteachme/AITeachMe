"""HTML reader using httpx and BeautifulSoup when available."""

from __future__ import annotations

import re

import httpx
import structlog

from app.shared.infra.search.readers.base import BaseReader
from app.shared.infra.search.readers.common import build_error_page, fetch_url, normalize_read_text
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)

_INVALID_PAGE_HINTS = (
    "文章不存在",
    "页面不存在",
    "内容不存在",
    "页面将在",
    "返回上一页",
    "立即跳转",
    "访问过于频繁",
    "请稍后再试",
)


def _looks_like_invalid_page(*, title: str, content: str) -> bool:
    normalized_title = " ".join(str(title or "").split())
    normalized_content = " ".join(str(content or "").split())
    if normalized_title in {"温馨提示", "提示", "404", "页面不存在"}:
        return True
    hit_count = sum(1 for hint in _INVALID_PAGE_HINTS if hint in normalized_content)
    return hit_count >= 2


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
            log_method = logger.info
            if not (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {403, 404, 429}):
                log_method = logger.warning
            log_method("bs4_read_failed", url=url, error=str(exc))
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
        normalized_content = normalize_read_text(content)
        if _looks_like_invalid_page(title=title, content=normalized_content):
            return ScrapedPage(
                url=url,
                title=title,
                content=normalized_content,
                content_type="text/html",
                reader_name=self.name,
                success=False,
                error="html page looks like an invalid/redirect/blocked notice",
            )
        return ScrapedPage(
            url=url,
            title=title,
            content=normalized_content,
            content_type="text/html",
            reader_name=self.name,
        )


__all__ = ["BS4Reader"]
