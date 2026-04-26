"""pdfplumber-based PDF parser — best for table-heavy documents.

pdfplumber (built on pdfminer.six) excels at:
- Precise table detection and extraction
- Character-level position analysis
- Complex layout preservation
- Better table-to-markdown conversion than PyMuPDF

Used as a specialized parser for table_pdf classification.
Falls back to pymupdf_native if pdfplumber is unavailable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.types import ParserRunOptions

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

logger = structlog.get_logger()

PDF_PDFPLUMBER_AVAILABLE = pdfplumber is not None


async def parse_pdf_with_pdfplumber(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse PDF with pdfplumber for best table extraction."""
    return await asyncio.to_thread(_parse_pdf_with_pdfplumber_sync, Path(file_path), asset_dir, options)


def _parse_pdf_with_pdfplumber_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    if pdfplumber is None:
        raise FileParseError(path.name, reason="pdfplumber is not available.")

    logger.info("parse_pdf_pdfplumber_start", filename=path.name)

    sections: list[str] = []

    with pdfplumber.open(str(path)) as pdf:
        total_pages = len(pdf.pages)
        logger.info("parse_pdf_pdfplumber_pages", filename=path.name, pages=total_pages)

        for page_idx, page in enumerate(pdf.pages):
            page_sections: list[str] = []
            page_num = page_idx + 1

            # Add page header
            page_sections.append(f"\n---\n\n## Page {page_num}\n")

            # Extract tables first (pdfplumber's strength)
            tables = page.extract_tables()
            table_bboxes = []

            if tables:
                for table_idx, table in enumerate(tables):
                    md_table = _table_to_markdown(table)
                    if md_table:
                        page_sections.append(md_table)

                # Get table bounding boxes for text exclusion
                table_settings = page.find_tables()
                table_bboxes = [t.bbox for t in table_settings] if table_settings else []

            # Extract text outside of tables
            if table_bboxes:
                # Crop page to exclude table regions and extract remaining text
                text = _extract_text_outside_tables(page, table_bboxes)
            else:
                text = page.extract_text() or ""

            if text.strip():
                page_sections.append(text.strip())

            sections.extend(page_sections)

    result = "\n\n".join(s for s in sections if s.strip())

    if not result.strip():
        raise FileParseError(path.name, reason="pdfplumber returned empty content.")

    logger.info("parse_pdf_pdfplumber_done", filename=path.name, chars=len(result), pages=total_pages)
    return result


def _extract_text_outside_tables(page, table_bboxes: list) -> str:
    """Extract text from page areas that don't overlap with tables."""
    try:
        # Filter out characters that fall within table bounding boxes
        chars_outside = []
        for char in page.chars:
            in_table = False
            for bbox in table_bboxes:
                x0, top, x1, bottom = bbox
                if (x0 <= char["x0"] <= x1 and top <= char["top"] <= bottom):
                    in_table = True
                    break
            if not in_table:
                chars_outside.append(char)

        if not chars_outside:
            return ""

        # Use pdfplumber's text extraction on filtered characters
        filtered_page = page.filter(
            lambda obj: obj["object_type"] != "char" or not _char_in_any_bbox(obj, table_bboxes)
        )
        return filtered_page.extract_text() or ""
    except Exception:
        # Fallback: just return full page text
        return page.extract_text() or ""


def _char_in_any_bbox(char: dict, bboxes: list) -> bool:
    """Check if a character falls within any of the given bounding boxes."""
    for bbox in bboxes:
        x0, top, x1, bottom = bbox
        if x0 <= char.get("x0", 0) <= x1 and top <= char.get("top", 0) <= bottom:
            return True
    return False


def _table_to_markdown(table: list[list]) -> str:
    """Convert a pdfplumber table to Markdown table format."""
    if not table or len(table) < 1:
        return ""

    # Clean cells
    cleaned = []
    for row in table:
        cleaned_row = [
            (cell or "").replace("\n", " ").strip()
            for cell in row
        ]
        cleaned.append(cleaned_row)

    if not cleaned:
        return ""

    # Determine column count (use max across all rows)
    max_cols = max(len(row) for row in cleaned) if cleaned else 0
    if max_cols == 0:
        return ""

    # Normalize all rows to same column count
    for row in cleaned:
        while len(row) < max_cols:
            row.append("")

    # Build markdown table
    lines = []
    # Header row
    header = cleaned[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")

    # Data rows
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)

