"""Generic MarkItDown parser for broad ingest format coverage."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from app.core.exceptions import FileParseError
from app.workflows.ingest.parsing.types import ParserRunOptions


try:
    from markitdown import MarkItDown
except ImportError:
    MarkItDown = None


logger = structlog.get_logger()

GENERIC_MARKITDOWN_AVAILABLE = MarkItDown is not None


async def parse_with_markitdown_generic(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse a non-core document format through MarkItDown."""

    del asset_dir
    del options
    return await asyncio.to_thread(_parse_with_markitdown_generic_sync, Path(file_path))


def _parse_with_markitdown_generic_sync(path: Path) -> str:
    if MarkItDown is None:
        raise FileParseError(path.name, reason="MarkItDown is not available.")

    logger.info("parse_markitdown_generic_start", filename=path.name, extension=path.suffix.lower())
    result = MarkItDown().convert(str(path))
    if not result.text_content or not result.text_content.strip():
        raise FileParseError(path.name, reason="MarkItDown generic parser returned empty markdown.")
    return result.text_content
