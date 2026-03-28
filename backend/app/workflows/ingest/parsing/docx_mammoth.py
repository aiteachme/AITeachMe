"""Mammoth-based DOCX parser — best for style-preserving HTML→Markdown conversion.

mammoth specializes in semantic DOCX conversion:
- Preserves heading hierarchy, lists, bold/italic
- Converts tables to HTML (which we then convert to Markdown tables)
- Handles footnotes and endnotes
- Better at style mapping than python-docx raw extraction

Used as the primary DOCX parser when available.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import structlog

from app.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.types import ParserRunOptions

try:
    import mammoth
except ImportError:
    mammoth = None

logger = structlog.get_logger()

DOCX_MAMMOTH_AVAILABLE = mammoth is not None


async def parse_docx_with_mammoth(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse DOCX with mammoth for best style preservation."""
    return await asyncio.to_thread(_parse_docx_with_mammoth_sync, Path(file_path), asset_dir, options)


def _parse_docx_with_mammoth_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    if mammoth is None:
        raise FileParseError(path.name, reason="mammoth is not available.")

    logger.info("parse_docx_mammoth_start", filename=path.name)

    with open(path, "rb") as f:
        result = mammoth.convert_to_markdown(f)

    markdown = result.value
    if not markdown or not markdown.strip():
        raise FileParseError(path.name, reason="mammoth returned empty markdown.")

    # Log any conversion warnings
    if result.messages:
        for msg in result.messages[:5]:
            logger.debug("mammoth_warning", filename=path.name, message=str(msg))

    # Clean up mammoth output
    markdown = _clean_mammoth_output(markdown)

    logger.info(
        "parse_docx_mammoth_done",
        filename=path.name,
        chars=len(markdown),
        warnings=len(result.messages),
    )

    # Supplement images from DOCX archive (mammoth doesn't extract them to disk)
    if not options.skip_image_supplement:
        from app.workflows.ingest.parsing.docx import supplement_docx_images
        supplement_docx_images(
            path,
            asset_dir,
            max_images=options.asset_image_limit,
            workers=options.parser_parallelism,
            asset_name_prefix=options.asset_name_prefix,
        )

    return markdown


def _clean_mammoth_output(markdown: str) -> str:
    """Clean common mammoth output artifacts."""
    # Remove excessive blank lines
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    # Fix heading spacing
    markdown = re.sub(r"(\n#{1,6} )", r"\n\1", markdown)
    return markdown.strip()
