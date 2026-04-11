"""PPTX reader using ZIP/XML parsing from the remote payload."""

from __future__ import annotations

import re
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

_SLIDE_NAME_PATTERN = re.compile(r"ppt/slides/slide(\d+)\.xml$")
_DRAWING_P_QNAME = "{http://schemas.openxmlformats.org/drawingml/2006/main}p"
_DRAWING_T_QNAME = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"


def extract_pptx_text(payload: bytes) -> tuple[str, str]:
    with open_zip_archive(payload) as archive:
        title = extract_core_title(archive)
        slide_blocks: list[str] = []
        slide_names = sorted(
            (name for name in archive.namelist() if _SLIDE_NAME_PATTERN.match(name)),
            key=lambda name: int(_SLIDE_NAME_PATTERN.match(name).group(1)),
        )
        for slide_index, member_name in enumerate(slide_names, start=1):
            with archive.open(member_name) as handle:
                paragraphs = extract_paragraphs_from_xml(
                    handle.read(),
                    paragraph_qname=_DRAWING_P_QNAME,
                    text_qname=_DRAWING_T_QNAME,
                )
            if not paragraphs:
                continue
            slide_blocks.append(f"Slide {slide_index}\n" + "\n".join(paragraphs))
        return title, normalize_scraped_text("\n\n".join(slide_blocks))


class PPTXScraper(BaseScraper):
    aliases = ("pptx",)
    priority = 94

    @property
    def name(self) -> str:
        return "pptx"

    @classmethod
    def supports_url(cls, url: str) -> bool:
        normalized = str(url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        return normalized.endswith(".pptx") or ".pptx?" in normalized

    async def scrape(self, url: str) -> ScrapedPage:
        content_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        try:
            response = await fetch_url(url)
        except Exception as exc:  # pragma: no cover - network/provider behavior
            logger.warning("pptx_scrape_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type=content_type, reader_name=self.name)

        try:
            title, content = extract_pptx_text(response.content)
        except Exception as exc:  # pragma: no cover - malformed provider payload
            logger.warning("pptx_parse_failed", url=url, error=str(exc))
            return build_error_page(url, error=exc, content_type=content_type, reader_name=self.name)

        return ScrapedPage(
            url=url,
            title=title,
            content=content,
            content_type=content_type,
            reader_name=self.name,
        )


__all__ = ["PPTXScraper", "extract_pptx_text"]



