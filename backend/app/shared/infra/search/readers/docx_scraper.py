"""DOCX reader using ZIP/XML parsing from the remote payload."""

from __future__ import annotations

import structlog

from app.shared.infra.search.readers.base import BaseScraper
from app.shared.infra.search.readers.common import (
    build_error_page,
    extract_core_title,
    extract_paragraphs_from_xml,
    fetch_url,
    normalize_scraped_text,
    open_zip_archive,
)
from app.shared.infra.search.types import ScrapedPage

logger = structlog.get_logger(__name__)

_WORD_P_QNAME = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
_WORD_T_QNAME = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def extract_docx_text(payload: bytes) -> tuple[str, str]:
    with open_zip_archive(payload) as archive:
        title = extract_core_title(archive)
        paragraphs: list[str] = []
        for member_name in ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml"):
            try:
                with archive.open(member_name) as handle:
                    paragraphs.extend(
                        extract_paragraphs_from_xml(
                            handle.read(),
                            paragraph_qname=_WORD_P_QNAME,
                            text_qname=_WORD_T_QNAME,
                        )
                    )
            except KeyError:
                continue
        return title, normalize_scraped_text("\n\n".join(paragraphs))


class DOCXScraper(BaseScraper):
    aliases = ("docx",)
    priority = 95

    @property
    def name(self) -> str:
        return "docx"

    @classmethod
    def supports_url(cls, url: str) -> bool:
        normalized = str(url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        return normalized.endswith(".docx") or ".docx?" in normalized

    async def scrape(self, url: str) -> ScrapedPage:
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        try:
            response = await fetch_url(url)
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("docx_scrape_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type=content_type, reader_name=self.name)

        try:
            title, content = extract_docx_text(response.content)
        except Exception as exc:  # pragma: no cover - malformed provider payload
            logger.warning("docx_parse_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type=content_type, reader_name=self.name)

        return ScrapedPage(
            url=url,
            title=title,
            content=content,
            content_type=content_type,
            reader_name=self.name,
        )


__all__ = ["DOCXScraper", "extract_docx_text"]



