"""PDF parser variants used by the ingest workflow."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel
import structlog

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.image import parse_image_bytes_with_llm_vision
from app.workflows.ingest.parsing.markdown_pages import MarkdownPageSection, join_markdown_pages
from app.workflows.ingest.parsing.types import ParserRunOptions
from app.workflows.ingest.parsing.utils import save_image_bytes


try:
    import fitz
except ImportError:
    fitz = None

try:
    from markitdown import MarkItDown
except ImportError:
    MarkItDown = None

try:
    import pymupdf4llm
except ImportError:
    pymupdf4llm = None


logger = structlog.get_logger()

PDF_PYMUPDF_NATIVE_AVAILABLE = fitz is not None
PDF_MARKITDOWN_AVAILABLE = MarkItDown is not None
PDF_PYMUPDF4LLM_AVAILABLE = pymupdf4llm is not None
PDF_PYMUPDF_OCR_VISION_AVAILABLE = fitz is not None


class _PDFOCRPage(BaseModel):
    page_number: int
    base_text: str = ""
    image_filename: str | None = None
    image_bytes: bytes | None = None


class _PDFImageCandidate(BaseModel):
    page_number: int
    image_index: int
    image_bytes: bytes
    image_ext: str
    name_hint: str


async def parse_pdf_with_pymupdf4llm(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse PDF with pymupdf4llm and supplement extracted images."""

    return await asyncio.to_thread(_parse_pdf_with_pymupdf4llm_sync, Path(file_path), asset_dir, options)


async def parse_pdf_with_markitdown(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse PDF with MarkItDown and supplement extracted images."""

    return await asyncio.to_thread(_parse_pdf_with_markitdown_sync, Path(file_path), asset_dir, options)


async def parse_pdf_with_pymupdf_native(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse PDF with native PyMuPDF and inline extracted images."""

    return await asyncio.to_thread(_parse_pdf_with_pymupdf_native_sync, Path(file_path), asset_dir, options)


async def parse_pdf_with_pymupdf_ocr_vision(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse PDF with native extraction plus page-level vision OCR for scanned content."""

    if fitz is None:
        raise FileParseError(Path(file_path).name, reason="PyMuPDF is not available.")

    path = Path(file_path)
    logger.info(
        "parse_pdf_ocr_vision_start",
        filename=path.name,
        parser_parallelism=options.parser_parallelism,
        llm_ocr_page_concurrency=options.llm_ocr_page_concurrency,
        ocr_page_limit=options.ocr_page_limit,
        ocr_language_mode=options.ocr_language_mode,
    )
    pages = await asyncio.to_thread(_build_pdf_ocr_pages, path, asset_dir, options)
    if not pages:
        raise FileParseError(path.name, reason="PDF OCR parser found no pages.")

    ocr_map = await _run_page_ocr(pages, options)
    sections: list[str] = []
    for page in pages:
        sections.append(f"<!-- page:{page.page_number} -->")
        if page.base_text.strip():
            sections.append(page.base_text.strip())
        ocr_text = ocr_map.get(page.page_number, "")
        if ocr_text:
            sections.append("### OCR Text")
            sections.append(ocr_text.strip())
        if page.image_filename:
            sections.append(f"![Page {page.page_number}]({page.image_filename})")
        sections.append("")

    result = "\n".join(sections).strip()
    if not result:
        raise FileParseError(path.name, reason="PDF OCR parser returned empty markdown.")
    return result


async def _run_page_ocr(
    pages: list[_PDFOCRPage],
    options: ParserRunOptions,
) -> dict[int, str]:
    semaphore = asyncio.Semaphore(max(1, options.llm_ocr_page_concurrency))
    ocr_map: dict[int, str] = {}

    async def _ocr_one(page: _PDFOCRPage) -> None:
        if page.image_bytes is None:
            return
        async with semaphore:
            text = await parse_image_bytes_with_llm_vision(
                page.image_bytes,
                mime_type="image/png",
                language_mode=options.ocr_language_mode,
            )
        ocr_map[page.page_number] = text

    await asyncio.gather(*[_ocr_one(page) for page in pages])
    return ocr_map


def _build_pdf_ocr_pages(path: Path, asset_dir: Path, options: ParserRunOptions) -> list[_PDFOCRPage]:
    if fitz is None:
        return []

    document = fitz.open(str(path))
    pages: list[_PDFOCRPage] = []
    ocr_pages = 0
    captured_pages = 0
    min_text_chars = max(options.ocr_text_char_threshold, 20)

    for page_index in range(len(document)):
        page = document[page_index]
        page_number = page_index + 1
        base_text = (page.get_text("text") or "").strip()
        has_visual = bool(page.get_images(full=True)) or _page_has_meaningful_drawing_clusters(page)
        should_ocr = (
            options.enable_page_vision_ocr
            and ocr_pages < options.ocr_page_limit
            and has_visual
            and len(base_text) < min_text_chars
        )
        if not should_ocr:
            if has_visual and len(base_text) < min_text_chars and captured_pages < options.asset_image_limit:
                page_bytes = _render_page_png(page)
                filename = save_image_bytes(
                    page_bytes,
                    asset_dir,
                    name_hint=f"page{page_number}_img",
                    ext=".png",
                    name_prefix=options.asset_name_prefix,
                )
                pages.append(
                    _PDFOCRPage(
                        page_number=page_number,
                        base_text=base_text,
                        image_filename=filename,
                    )
                )
                captured_pages += 1
            else:
                pages.append(_PDFOCRPage(page_number=page_number, base_text=base_text))
            continue

        page_bytes = _render_page_png(page)
        filename = save_image_bytes(
            page_bytes,
            asset_dir,
            name_hint=f"page{page_number}_ocr",
            ext=".png",
            name_prefix=options.asset_name_prefix,
        )
        pages.append(
            _PDFOCRPage(
                page_number=page_number,
                base_text=base_text,
                image_filename=filename,
                image_bytes=page_bytes,
            )
        )
        ocr_pages += 1
        captured_pages += 1

    document.close()
    return pages


def _parse_pdf_with_pymupdf4llm_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    if pymupdf4llm is None:
        raise FileParseError(path.name, reason="pymupdf4llm is not available.")

    logger.info("parse_pdf_pymupdf4llm_start", filename=path.name, parser_parallelism=options.parser_parallelism)
    text = _render_pymupdf4llm_markdown(path)
    if not text or not text.strip():
        raise FileParseError(path.name, reason="pymupdf4llm returned empty markdown.")

    if not options.skip_image_supplement:
        supplement_pdf_images(
            path,
            asset_dir,
            max_images=options.asset_image_limit,
            workers=options.parser_parallelism,
            asset_name_prefix=options.asset_name_prefix,
        )
    return text


def _render_pymupdf4llm_markdown(path: Path) -> str:
    """Request page chunks so downstream placeholder recovery can stay page-aware."""

    chunked_result = pymupdf4llm.to_markdown(str(path), page_chunks=True)
    if isinstance(chunked_result, list):
        sections: list[MarkdownPageSection] = []
        for index, chunk in enumerate(chunked_result, start=1):
            metadata = chunk.get("metadata", {})
            page_number = int(metadata.get("page_number") or index)
            text = str(chunk.get("text") or "").strip()
            sections.append(
                MarkdownPageSection(
                    page_number=page_number,
                    marker=f"<!-- page:{page_number} -->",
                    body=text,
                )
            )
        rendered = join_markdown_pages(sections)
        if rendered.strip():
            return rendered

    fallback_text = pymupdf4llm.to_markdown(str(path))
    return fallback_text.strip()


def _parse_pdf_with_markitdown_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    if MarkItDown is None:
        raise FileParseError(path.name, reason="MarkItDown is not available.")

    logger.info("parse_pdf_markitdown_start", filename=path.name, parser_parallelism=options.parser_parallelism)
    result = MarkItDown().convert(str(path))
    if not result.text_content or not result.text_content.strip():
        raise FileParseError(path.name, reason="MarkItDown returned empty markdown.")

    if not options.skip_image_supplement:
        supplement_pdf_images(
            path,
            asset_dir,
            max_images=options.asset_image_limit,
            workers=options.parser_parallelism,
            asset_name_prefix=options.asset_name_prefix,
        )
    return result.text_content


def _parse_pdf_with_pymupdf_native_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    if fitz is None:
        raise FileParseError(path.name, reason="PyMuPDF is not available.")

    logger.info("parse_pdf_native_start", filename=path.name, parser_parallelism=options.parser_parallelism)
    document = fitz.open(str(path))
    sections: list[str] = []
    image_candidates: list[_PDFImageCandidate] = []
    seen_xref: set[int] = set()

    for page_index in range(len(document)):
        page = document[page_index]
        page_number = page_index + 1
        sections.append(f"<!-- page:{page_number} -->")

        text = page.get_text("text")
        if text and text.strip():
            sections.append(text.strip())

        # 先提取 embedded images
        page_image_start = len(image_candidates)
        _append_pdf_image_candidates(
            document,
            page,
            page_number=page_number,
            max_images=options.asset_image_limit,
            candidates=image_candidates,
            seen_xref=seen_xref,
        )

        # 再提取 drawings
        page_drawing_start = len(image_candidates)
        _append_pdf_drawing_candidates(
            page,
            page_number=page_number,
            max_images=options.asset_image_limit,
            candidates=image_candidates,
        )

        # 如果当前页有提取的图片，立即插入到该页内容后
        page_images = image_candidates[page_image_start:]
        if page_images:
            # 保存并插入当前页的图片
            page_image_names = _save_pdf_images_parallel(
                page_images,
                asset_dir,
                workers=options.parser_parallelism,
                asset_name_prefix=options.asset_name_prefix,
            )
            for idx, image_name in enumerate(page_image_names, start=1):
                if image_name:
                    sections.append(f"![Extracted image {idx}](../assets/{image_name})")

        sections.append("")
        if len(image_candidates) >= options.asset_image_limit:
            logger.info(
                "parse_pdf_native_image_limit_reached",
                filename=path.name,
                limit=options.asset_image_limit,
            )
            break

    document.close()

    result = "\n".join(sections).strip()
    if not result:
        raise FileParseError(path.name, reason="PyMuPDF returned empty markdown.")

    logger.info(
        "parse_pdf_native_done",
        filename=path.name,
        total_images=len(image_candidates),
        embedded_images=len([c for c in image_candidates if c.name_hint.startswith("p") and "_img" in c.name_hint]),
        drawings=len([c for c in image_candidates if "_draw" in c.name_hint]),
    )
    return result


def supplement_pdf_images(
    file_path: Path,
    asset_dir: Path,
    *,
    max_images: int,
    workers: int,
    asset_name_prefix: str,
) -> None:
    """Extract images when markdown came from a non-native parser."""

    if fitz is None:
        return

    document = fitz.open(str(file_path))
    seen_xref: set[int] = set()
    candidates: list[_PDFImageCandidate] = []
    for page_index in range(len(document)):
        page = document[page_index]
        _append_pdf_image_candidates(
            document,
            page,
            page_number=page_index + 1,
            max_images=max_images,
            candidates=candidates,
            seen_xref=seen_xref,
        )
        _append_pdf_drawing_candidates(
            page,
            page_number=page_index + 1,
            max_images=max_images,
            candidates=candidates,
        )
        if len(candidates) >= max_images:
            document.close()
            _save_pdf_images_parallel(
                candidates,
                asset_dir,
                workers=workers,
                asset_name_prefix=asset_name_prefix,
            )
            logger.info("pdf_images_supplement_limited", filename=file_path.name, limit=max_images)
            return

    document.close()
    names = _save_pdf_images_parallel(
        candidates,
        asset_dir,
        workers=workers,
        asset_name_prefix=asset_name_prefix,
    )
    if names:
        logger.info("pdf_images_supplemented", filename=file_path.name, count=len([name for name in names if name]))


def _save_pdf_images_parallel(
    candidates: list[_PDFImageCandidate],
    asset_dir: Path,
    *,
    workers: int,
    asset_name_prefix: str,
) -> list[str]:
    if not candidates:
        return []

    max_workers = min(max(workers, 1), 10)
    if max_workers == 1:
        return [_save_pdf_candidate(candidate, asset_dir, asset_name_prefix) for candidate in candidates]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_save_pdf_candidate, candidate, asset_dir, asset_name_prefix)
            for candidate in candidates
        ]
        return [future.result() for future in futures]


def _save_pdf_candidate(candidate: _PDFImageCandidate, asset_dir: Path, asset_name_prefix: str) -> str:
    return save_image_bytes(
        candidate.image_bytes,
        asset_dir,
        name_hint=candidate.name_hint,
        ext=f".{candidate.image_ext}",
        name_prefix=asset_name_prefix,
    )


def _render_page_png(page: object) -> bytes:
    if fitz is None:
        return b""
    matrix = fitz.Matrix(2.0, 2.0)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    return pixmap.tobytes("png")


def _extract_pdf_image(document: object, xref: int) -> tuple[bytes, str] | None:
    try:
        base_image = document.extract_image(xref)
    except Exception:
        return None
    if base_image is None:
        return None
    return base_image["image"], base_image.get("ext", "png")


def _append_pdf_image_candidates(
    document: object,
    page: object,
    *,
    page_number: int,
    max_images: int,
    candidates: list[_PDFImageCandidate],
    seen_xref: set[int],
) -> None:
    for image_index, image_info in enumerate(page.get_images(full=True), start=1):
        if len(candidates) >= max_images:
            return
        xref = int(image_info[0])
        if xref in seen_xref:
            continue
        seen_xref.add(xref)
        base_image = _extract_pdf_image(document, xref)
        if base_image is None:
            continue
        image_bytes, image_ext = base_image
        if len(image_bytes) < 2048:
            continue
        candidates.append(
            _PDFImageCandidate(
                page_number=page_number,
                image_index=image_index,
                image_bytes=image_bytes,
                image_ext=image_ext,
                name_hint=f"p{page_number}_img{image_index}",
            )
        )


def _append_pdf_drawing_candidates(
    page: object,
    *,
    page_number: int,
    max_images: int,
    candidates: list[_PDFImageCandidate],
) -> None:
    for drawing_index, rect in enumerate(page.cluster_drawings(), start=1):
        if len(candidates) >= max_images:
            return
        if not _is_meaningful_drawing_rect(rect):
            continue
        image_bytes = _render_rect_png(page, rect)
        if len(image_bytes) < 2048:
            continue
        candidates.append(
            _PDFImageCandidate(
                page_number=page_number,
                image_index=drawing_index,
                image_bytes=image_bytes,
                image_ext="png",
                name_hint=f"p{page_number}_draw{drawing_index}",
            )
        )


def _page_has_meaningful_drawing_clusters(page: object) -> bool:
    return any(_is_meaningful_drawing_rect(rect) for rect in page.cluster_drawings())


def _is_meaningful_drawing_rect(rect: object) -> bool:
    width = float(rect.width)
    height = float(rect.height)
    area = width * height
    return width >= 40 and height >= 10 and area >= 1500


def _render_rect_png(page: object, rect: object) -> bytes:
    if fitz is None:
        return b""

    padding = 6
    clip = fitz.Rect(
        max(page.rect.x0, rect.x0 - padding),
        max(page.rect.y0, rect.y0 - padding),
        min(page.rect.x1, rect.x1 + padding),
        min(page.rect.y1, rect.y1 + padding),
    )
    pixmap = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0), clip=clip, alpha=False)
    return pixmap.tobytes("png")
