"""Asset-level OCR enrichment for parsed markdown."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from pathlib import Path
import re
from urllib.parse import unquote

from pydantic import BaseModel
import structlog

from app.services.upload_support import list_asset_files
from app.workflows.ingest.parsing.image import parse_image_bytes_with_llm_vision
from app.workflows.ingest.parsing.markdown_pages import MarkdownPageSection, join_markdown_pages, split_markdown_pages
from app.workflows.ingest.parsing.utils import MIME_MAP

logger = structlog.get_logger()

_PLACEHOLDER_LINE_RE = re.compile(
    r"^[^\n]*(?:picture|image)\s*\[[^\]]+\]\s*intentionally omitted[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?P<target>[^)]+)\)")
_HTML_IMAGE_RE = re.compile(r'<img\b[^>]*?\bsrc=["\'](?P<target>[^"\']+)["\']', re.IGNORECASE)
_ASSET_PAGE_NUMBER_RE = re.compile(r"(?:^|__)(?:p|page)(?P<page>\d+)_", re.IGNORECASE)


class AssetOCRItem(BaseModel):
    """OCR payload for one extracted asset."""

    filename: str
    markdown_url: str
    ocr_markdown: str
    page_number: int | None = None


class AssetOCREnhancementResult(BaseModel):
    """Markdown plus asset OCR enrichment stats."""

    markdown: str
    ocr_image_count: int = 0
    placeholder_replacements: int = 0


async def enhance_markdown_with_asset_ocr(
    markdown: str,
    *,
    asset_dir: Path,
    asset_link_prefix: str,
    asset_name_prefix: str,
    enabled: bool,
    limit: int,
    language_mode: str,
    concurrency: int,
) -> AssetOCREnhancementResult:
    """Enrich parsed markdown with OCR from extracted images."""

    if not markdown.strip() or limit <= 0:
        return AssetOCREnhancementResult(markdown=markdown)

    asset_paths = list_asset_files(asset_dir, asset_name_prefix=asset_name_prefix)
    if not asset_paths:
        return AssetOCREnhancementResult(markdown=markdown)

    placeholder_count = len(list(_PLACEHOLDER_LINE_RE.finditer(markdown)))
    if not enabled and placeholder_count == 0:
        return AssetOCREnhancementResult(markdown=markdown)

    referenced_assets = _collect_referenced_asset_names(markdown)
    candidate_paths = (
        asset_paths[: min(len(asset_paths), max(limit, min(placeholder_count, 24)))]
        if placeholder_count
        else [path for path in asset_paths if path.name not in referenced_assets][:limit]
    )
    if not candidate_paths:
        return AssetOCREnhancementResult(markdown=markdown)

    if enabled:
        ocr_items = await _ocr_asset_paths(
            candidate_paths,
            asset_link_prefix=asset_link_prefix,
            language_mode=language_mode,
            concurrency=concurrency,
        )
    else:
        ocr_items = [_build_plain_asset_item(asset_path, asset_link_prefix=asset_link_prefix) for asset_path in candidate_paths]
    if not ocr_items:
        if placeholder_count:
            ocr_items = [_build_plain_asset_item(asset_path, asset_link_prefix=asset_link_prefix) for asset_path in candidate_paths]
        else:
            return AssetOCREnhancementResult(markdown=markdown)

    if not ocr_items:
        return AssetOCREnhancementResult(markdown=markdown)

    enhanced_markdown, replacement_count = _replace_placeholder_lines(markdown, ocr_items)
    if replacement_count == 0:
        enhanced_markdown = _append_ocr_appendix(enhanced_markdown, ocr_items)

    if enhanced_markdown and not enhanced_markdown.endswith("\n"):
        enhanced_markdown = f"{enhanced_markdown}\n"

    logger.info(
        "asset_ocr_enhanced_markdown",
        asset_candidates=len(candidate_paths),
        ocr_images=len(ocr_items),
        placeholder_count=placeholder_count,
        placeholder_replacements=replacement_count,
    )
    return AssetOCREnhancementResult(
        markdown=enhanced_markdown,
        ocr_image_count=len(ocr_items),
        placeholder_replacements=replacement_count,
    )


async def _ocr_asset_paths(
    asset_paths: list[Path],
    *,
    asset_link_prefix: str,
    language_mode: str,
    concurrency: int,
) -> list[AssetOCRItem]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[AssetOCRItem | None] = [None] * len(asset_paths)

    async def _ocr_one(index: int, asset_path: Path) -> None:
        mime_type = MIME_MAP.get(asset_path.suffix.lower(), "image/png")
        image_bytes = asset_path.read_bytes()
        async with semaphore:
            try:
                ocr_markdown = await parse_image_bytes_with_llm_vision(
                    image_bytes,
                    mime_type=mime_type,
                    language_mode=language_mode,
                )
            except Exception as exc:
                logger.warning(
                    "asset_ocr_failed",
                    asset_name=asset_path.name,
                    error=str(exc),
                )
                return

        results[index] = AssetOCRItem(
            filename=asset_path.name,
            markdown_url=f"{asset_link_prefix}/{asset_path.name}",
            ocr_markdown=ocr_markdown.strip(),
            page_number=_extract_asset_page_number(asset_path.name),
        )

    await asyncio.gather(*[_ocr_one(index, asset_path) for index, asset_path in enumerate(asset_paths)])
    return [item for item in results if item is not None]


def _build_plain_asset_item(asset_path: Path, *, asset_link_prefix: str) -> AssetOCRItem:
    return AssetOCRItem(
        filename=asset_path.name,
        markdown_url=f"{asset_link_prefix}/{asset_path.name}",
        ocr_markdown="",
        page_number=_extract_asset_page_number(asset_path.name),
    )


def _collect_referenced_asset_names(markdown: str) -> set[str]:
    names: set[str] = set()
    for match in _MARKDOWN_IMAGE_RE.finditer(markdown):
        asset_name = _extract_asset_name(match.group("target"))
        if asset_name:
            names.add(asset_name)
    for match in _HTML_IMAGE_RE.finditer(markdown):
        asset_name = _extract_asset_name(match.group("target"))
        if asset_name:
            names.add(asset_name)
    return names


def _extract_asset_name(target: str) -> str | None:
    cleaned = target.strip().strip("<>").split(" ", 1)[0]
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if "../assets/" not in lowered and "/_assets/" not in lowered:
        return None
    return Path(unquote(cleaned)).name


def _extract_asset_page_number(filename: str) -> int | None:
    match = _ASSET_PAGE_NUMBER_RE.search(filename)
    if match is None:
        return None
    return int(match.group("page"))


def _replace_placeholder_lines(markdown: str, ocr_items: list[AssetOCRItem]) -> tuple[str, int]:
    if not ocr_items:
        return markdown, 0

    page_sections = split_markdown_pages(markdown)
    if page_sections:
        return _replace_placeholder_lines_by_page(page_sections, ocr_items)

    # 非分页模式：按顺序替换占位符
    replacement_index = 0
    lines: list[str] = []
    for line in markdown.splitlines():
        if _PLACEHOLDER_LINE_RE.match(line) and replacement_index < len(ocr_items):
            lines.append(_render_ocr_block(ocr_items[replacement_index], replacement_index + 1))
            replacement_index += 1
            continue
        lines.append(line)

    result = "\n".join(lines).strip()
    return result, replacement_index


def _replace_placeholder_lines_by_page(
    page_sections: list[MarkdownPageSection],
    ocr_items: list[AssetOCRItem],
) -> tuple[str, int]:
    page_queues: dict[int, deque[AssetOCRItem]] = defaultdict(deque)
    shared_queue: deque[AssetOCRItem] = deque()
    for item in ocr_items:
        if item.page_number is None:
            shared_queue.append(item)
            continue
        page_queues[item.page_number].append(item)

    replacement_index = 0
    rebuilt_sections = []
    for section in page_sections:
        lines: list[str] = []
        page_queue = page_queues.get(section.page_number, deque())
        for line in section.body.splitlines():
            if not _PLACEHOLDER_LINE_RE.match(line):
                lines.append(line)
                continue

            item = page_queue.popleft() if page_queue else None
            if item is None and shared_queue:
                item = shared_queue.popleft()
            if item is None:
                lines.append(line)
                continue

            replacement_index += 1
            lines.append(_render_ocr_block(item, replacement_index))

        section.body = "\n".join(lines)
        rebuilt_sections.append(section)

    enhanced_markdown = join_markdown_pages(rebuilt_sections)
    if enhanced_markdown:
        return enhanced_markdown, replacement_index
    return "", replacement_index


def _append_ocr_appendix(markdown: str, ocr_items: list[AssetOCRItem]) -> str:
    appendix_lines = [
        markdown.strip(),
        "",
        "## Extracted Image OCR",
        "",
    ]
    for index, item in enumerate(ocr_items, start=1):
        appendix_lines.extend(
            [
                f"### Image {index}",
                "",
                _render_ocr_block(item, index),
                "",
            ]
        )
    return "\n".join(line for line in appendix_lines if line is not None).strip()


def _render_ocr_block(item: AssetOCRItem, index: int) -> str:
    parts = [f"![Extracted image {index}]({item.markdown_url})"]
    if item.ocr_markdown and item.ocr_markdown.strip() and item.ocr_markdown.strip() != "[unclear]":
        parts.extend(["", "```markdown", item.ocr_markdown.strip(), "```"])
    return "\n".join(parts)
