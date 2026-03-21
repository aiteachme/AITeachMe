"""PDF parser variants used by the ingest workflow."""

from __future__ import annotations

from pathlib import Path

import structlog

from app.core.exceptions import FileParseError
from app.workflows.ingest.parse_utils import save_image_bytes


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


async def parse_pdf_with_pymupdf4llm(file_path: str | Path, asset_dir: Path) -> str:
    """Parse PDF with pymupdf4llm and supplement extracted images."""

    path = Path(file_path)
    if pymupdf4llm is None:
        raise FileParseError(path.name, reason="pymupdf4llm is not available.")

    logger.info("parse_pdf_pymupdf4llm_start", filename=path.name)
    text = pymupdf4llm.to_markdown(str(path))
    if not text or not text.strip():
        raise FileParseError(path.name, reason="pymupdf4llm returned empty markdown.")

    supplement_pdf_images(path, asset_dir)
    return text


async def parse_pdf_with_markitdown(file_path: str | Path, asset_dir: Path) -> str:
    """Parse PDF with MarkItDown and supplement extracted images."""

    path = Path(file_path)
    if MarkItDown is None:
        raise FileParseError(path.name, reason="MarkItDown is not available.")

    logger.info("parse_pdf_markitdown_start", filename=path.name)
    result = MarkItDown().convert(str(path))
    if not result.text_content or not result.text_content.strip():
        raise FileParseError(path.name, reason="MarkItDown returned empty markdown.")

    supplement_pdf_images(path, asset_dir)
    return result.text_content


async def parse_pdf_with_pymupdf_native(file_path: str | Path, asset_dir: Path) -> str:
    """Parse PDF with native PyMuPDF and inline extracted images."""

    path = Path(file_path)
    if fitz is None:
        raise FileParseError(path.name, reason="PyMuPDF is not available.")

    logger.info("parse_pdf_native_start", filename=path.name)
    document = fitz.open(str(path))
    sections: list[str] = []
    image_count = 0

    for page_index in range(len(document)):
        page = document[page_index]
        page_number = page_index + 1
        sections.append(f"<!-- page:{page_number} -->")

        text = page.get_text("text")
        if text and text.strip():
            sections.append(text.strip())

        for image_index, image_info in enumerate(page.get_images(full=True), start=1):
            base_image = _extract_pdf_image(document, image_info[0])
            if base_image is None:
                continue

            image_bytes, image_ext = base_image
            if len(image_bytes) < 2048:
                continue

            image_count += 1
            filename = save_image_bytes(
                image_bytes,
                asset_dir,
                name_hint=f"p{page_number}_img{image_index}",
                ext=f".{image_ext}",
            )
            sections.append(f"![Image {image_count}]({filename})")

        sections.append("")

    document.close()
    result = "\n".join(sections).strip()
    if not result:
        raise FileParseError(path.name, reason="PyMuPDF returned empty markdown.")

    logger.info("parse_pdf_native_done", filename=path.name, images=image_count)
    return result


def supplement_pdf_images(file_path: Path, asset_dir: Path) -> None:
    """Extract images when markdown came from a non-native parser."""

    if fitz is None:
        return

    document = fitz.open(str(file_path))
    count = 0
    for page_index in range(len(document)):
        page = document[page_index]
        for image_index, image_info in enumerate(page.get_images(full=True), start=1):
            base_image = _extract_pdf_image(document, image_info[0])
            if base_image is None:
                continue

            image_bytes, image_ext = base_image
            if len(image_bytes) < 2048:
                continue

            save_image_bytes(
                image_bytes,
                asset_dir,
                name_hint=f"p{page_index + 1}_img{image_index}",
                ext=f".{image_ext}",
            )
            count += 1

    document.close()
    if count:
        logger.info("pdf_images_supplemented", filename=file_path.name, count=count)


def _extract_pdf_image(document: object, xref: int) -> tuple[bytes, str] | None:
    try:
        base_image = document.extract_image(xref)
    except Exception:
        return None
    if base_image is None:
        return None
    return base_image["image"], base_image.get("ext", "png")
