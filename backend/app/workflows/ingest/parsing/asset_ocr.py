"""Asset-level OCR enrichment for parsed markdown."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from pathlib import Path
import re
from urllib.parse import unquote

from pydantic import BaseModel
import structlog

from app.utils.path_helpers import list_asset_files
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
    # OCR Budget Control (改进 6: MinerU coarse-to-fine 思路)
    # Skip tiny/decorative images that waste LLM API calls
    candidate_paths = [p for p in candidate_paths if _should_ocr_image(p)]
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


# ── OCR Budget Control (改进 6: MinerU coarse-to-fine 思路) ──

_MIN_OCR_FILE_SIZE = 2048  # 2KB — smaller files are likely icons/logos
_MIN_OCR_DIMENSION = 80    # pixels — images smaller than this are decorative
_MAX_OCR_ASPECT_RATIO = 8  # width/height or height/width — catch separators/lines


def _should_ocr_image(path: Path) -> bool:
    """Determine if an image is worth sending to LLM OCR.

    Filters out decorative images (logos, separators, tiny icons) that would
    waste LLM API calls without providing useful text content.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return False

    # Too small — likely an icon or logo
    if size < _MIN_OCR_FILE_SIZE:
        logger.debug("ocr_budget_skip_small", path=path.name, size=size)
        return False

    # Check dimensions if PIL is available
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
    except Exception:
        return True  # Can't check dimensions, assume it's worth OCR

    # Too small in pixels
    if w < _MIN_OCR_DIMENSION or h < _MIN_OCR_DIMENSION:
        logger.debug("ocr_budget_skip_tiny_pixels", path=path.name, w=w, h=h)
        return False

    # Extreme aspect ratio — likely a separator/divider line
    ratio = max(w / h, h / w) if h > 0 and w > 0 else 1
    if ratio > _MAX_OCR_ASPECT_RATIO:
        logger.debug("ocr_budget_skip_ratio", path=path.name, w=w, h=h, ratio=round(ratio, 1))
        return False

    return True


async def _ocr_asset_paths(
    asset_paths: list[Path],
    *,
    asset_link_prefix: str,
    language_mode: str,
    concurrency: int,
) -> list[AssetOCRItem]:
    """OCR asset images via LLM vision, with circuit breaker.

    If the vision model refuses/fails on 2 consecutive images,
    stops all remaining OCR attempts immediately (circuit breaker).
    This prevents wasting minutes on a model that can't do vision.
    """
    _CIRCUIT_BREAKER_THRESHOLD = 2  # consecutive failures to trigger stop
    consecutive_failures = 0
    stop_event = asyncio.Event()
    failure_lock = asyncio.Lock()
    pending_queue: asyncio.Queue[tuple[int, Path]] = asyncio.Queue()
    results: list[AssetOCRItem | None] = [None] * len(asset_paths)

    for index, asset_path in enumerate(asset_paths):
        pending_queue.put_nowait((index, asset_path))

    async def _record_failure(*, reason: str, asset_name: str, error: str | None = None) -> None:
        nonlocal consecutive_failures

        async with failure_lock:
            consecutive_failures += 1
            if error:
                logger.warning("asset_ocr_failed", asset_name=asset_name, error=error)
            if consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
                return
            if stop_event.is_set():
                return
            stop_event.set()
            logger.warning(
                "ocr_circuit_breaker_triggered",
                reason=reason,
                failed_count=consecutive_failures,
                remaining_skipped=pending_queue.qsize(),
                hint=(
                    "文档 OCR 模型可能不支持图片输入，请检查 settings.models.ocr 配置。"
                    if reason == "vision_model_refused"
                    else None
                ),
            )

    async def _record_success() -> None:
        nonlocal consecutive_failures
        async with failure_lock:
            consecutive_failures = 0

    async def _run_one(index: int, asset_path: Path) -> None:
        mime_type = MIME_MAP.get(asset_path.suffix.lower(), "image/png")
        try:
            image_bytes = asset_path.read_bytes()
        except OSError as exc:
            logger.warning("asset_ocr_read_failed", asset_name=asset_path.name, error=str(exc))
            return

        try:
            ocr_markdown = await parse_image_bytes_with_llm_vision(
                image_bytes,
                mime_type=mime_type,
                language_mode=language_mode,
                model_selector="ocr",
            )
        except Exception as exc:
            await _record_failure(reason="consecutive_failures", asset_name=asset_path.name, error=str(exc))
            return

        cleaned = ocr_markdown.strip()
        if cleaned == "[unclear]":
            await _record_failure(reason="vision_model_refused", asset_name=asset_path.name)
            return

        await _record_success()
        results[index] = AssetOCRItem(
            filename=asset_path.name,
            markdown_url=f"{asset_link_prefix}/{asset_path.name}",
            ocr_markdown=cleaned,
            page_number=_extract_asset_page_number(asset_path.name),
        )

    async def _worker() -> None:
        while not stop_event.is_set():
            try:
                index, asset_path = pending_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if stop_event.is_set():
                return
            await _run_one(index, asset_path)

    worker_count = max(1, min(int(concurrency or 1), len(asset_paths)))
    await asyncio.gather(*(_worker() for _ in range(worker_count)))
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
