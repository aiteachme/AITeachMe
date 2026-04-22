"""Page-level fallback for PDF placeholder recovery."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re

from pydantic import BaseModel
import structlog

from app.workflows.ingest.common.parsing.image import parse_image_bytes_with_llm_vision
from app.workflows.ingest.common.parsing.markdown_pages import MarkdownPageSection, join_markdown_pages, split_markdown_pages
from app.workflows.ingest.common.parsing.utils import save_image_bytes


try:
    import fitz
except ImportError:
    fitz = None


logger = structlog.get_logger()

_PLACEHOLDER_LINE_RE = re.compile(
    r"^[^\n]*(?:picture|image)\s*\[[^\]]+\]\s*intentionally omitted[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)


class PDFPageFallbackItem(BaseModel):
    """Rendered fallback for one PDF page."""

    page_number: int
    markdown_url: str
    ocr_markdown: str = ""


class PDFPageFallbackResult(BaseModel):
    """Markdown plus page-level placeholder fallback stats."""

    markdown: str
    page_image_count: int = 0
    placeholder_replacements: int = 0


async def enhance_pdf_markdown_with_page_fallback(
    markdown: str,
    *,
    pdf_path: Path,
    asset_dir: Path,
    asset_link_prefix: str,
    asset_name_prefix: str,
    enabled: bool,
    language_mode: str,
    concurrency: int,
    max_pages: int,
) -> PDFPageFallbackResult:
    """Replace remaining omitted placeholders with full-page fallback images."""

    if not markdown.strip() or fitz is None or max_pages <= 0:
        return PDFPageFallbackResult(markdown=markdown)

    target_pages = _collect_pages_with_placeholders(markdown)[:max_pages]
    if not target_pages:
        return PDFPageFallbackResult(markdown=markdown)

    rendered_pages = _render_page_items(
        pdf_path,
        asset_dir=asset_dir,
        asset_link_prefix=asset_link_prefix,
        asset_name_prefix=asset_name_prefix,
        page_numbers=target_pages,
    )
    if not rendered_pages:
        return PDFPageFallbackResult(markdown=markdown)

    if enabled:
        await _fill_page_ocr(
            rendered_pages,
            pdf_path=pdf_path,
            language_mode=language_mode,
            concurrency=concurrency,
        )

    enhanced_markdown, replacement_count = _replace_page_placeholders(markdown, rendered_pages)
    logger.info(
        "pdf_page_fallback_enhanced",
        page_count=len(rendered_pages),
        placeholder_replacements=replacement_count,
        enabled_ocr=enabled,
    )
    return PDFPageFallbackResult(
        markdown=enhanced_markdown,
        page_image_count=len(rendered_pages),
        placeholder_replacements=replacement_count,
    )


def _collect_pages_with_placeholders(markdown: str) -> list[int]:
    return [
        section.page_number
        for section in split_markdown_pages(markdown)
        if _PLACEHOLDER_LINE_RE.search(section.body)
    ]


def _render_page_items(
    pdf_path: Path,
    *,
    asset_dir: Path,
    asset_link_prefix: str,
    asset_name_prefix: str,
    page_numbers: list[int],
) -> dict[int, PDFPageFallbackItem]:
    if fitz is None:
        return {}

    document = fitz.open(str(pdf_path))
    items: dict[int, PDFPageFallbackItem] = {}
    try:
        for page_number in page_numbers:
            if page_number < 1 or page_number > len(document):
                continue
            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            page_bytes = pixmap.tobytes("png")
            filename = save_image_bytes(
                page_bytes,
                asset_dir,
                name_hint=f"page{page_number}_fallback",
                ext=".png",
                name_prefix=asset_name_prefix,
            )
            items[page_number] = PDFPageFallbackItem(
                page_number=page_number,
                markdown_url=f"{asset_link_prefix}/{filename}",
            )
    finally:
        document.close()
    return items


async def _fill_page_ocr(
    rendered_pages: dict[int, PDFPageFallbackItem],
    *,
    pdf_path: Path,
    language_mode: str,
    concurrency: int,
) -> None:
    """Fill OCR text for rendered pages, with circuit breaker.

    Stops after 2 consecutive [unclear] results to avoid wasting LLM calls
    when the vision model can't process images.
    """
    if fitz is None or not rendered_pages:
        return

    _CIRCUIT_BREAKER_THRESHOLD = 2
    consecutive_failures = 0

    document = fitz.open(str(pdf_path))
    try:
        for page_number in rendered_pages:
            if consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
                logger.warning(
                    "page_ocr_circuit_breaker_triggered",
                    reason="vision_model_refused",
                    failed_count=consecutive_failures,
                    remaining_skipped=len(rendered_pages) - list(rendered_pages.keys()).index(page_number),
                    hint="文档 OCR 模型可能不支持图片输入，请检查 settings.models.ocr 配置。",
                )
                break

            page = document[page_number - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
            page_bytes = pixmap.tobytes("png")
            try:
                result = await parse_image_bytes_with_llm_vision(
                    page_bytes,
                    mime_type="image/png",
                    language_mode=language_mode,
                    model_selector="ocr",
                )
                result = result.strip()
            except Exception as exc:
                logger.warning("pdf_page_fallback_ocr_failed", page_number=page_number, error=str(exc))
                consecutive_failures += 1
                continue

            if result == "[unclear]":
                consecutive_failures += 1
                continue
            else:
                consecutive_failures = 0
                rendered_pages[page_number].ocr_markdown = result
    finally:
        document.close()


def _replace_page_placeholders(
    markdown: str,
    rendered_pages: dict[int, PDFPageFallbackItem],
) -> tuple[str, int]:
    page_sections = split_markdown_pages(markdown)
    if not page_sections:
        return markdown, 0

    rebuilt_sections: list[MarkdownPageSection] = []
    replacements = 0

    for section in page_sections:
        item = rendered_pages.get(section.page_number)
        if item is None or not _PLACEHOLDER_LINE_RE.search(section.body):
            rebuilt_sections.append(section)
            continue

        section_lines: list[str] = []
        inserted = False
        for line in section.body.splitlines():
            if _PLACEHOLDER_LINE_RE.match(line):
                if not inserted:
                    section_lines.append(_render_page_block(item))
                    inserted = True
                replacements += 1
                continue
            section_lines.append(line)
        section.body = "\n".join(section_lines)
        rebuilt_sections.append(section)

    return join_markdown_pages(rebuilt_sections), replacements


def _render_page_block(item: PDFPageFallbackItem) -> str:
    parts = [f"![Page {item.page_number} fallback]({item.markdown_url})"]
    if item.ocr_markdown:
        parts.extend(["", "### Page OCR", item.ocr_markdown])
    return "\n".join(parts)
