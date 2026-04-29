"""MarkItDown PDF parser used by the active ingest local fallback."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.types import ParserRunOptions

logger = structlog.get_logger()


async def parse_pdf_with_markitdown(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse PDF through MarkItDown without importing legacy PDF parser stacks."""

    return await asyncio.to_thread(_parse_pdf_with_markitdown_sync, Path(file_path), asset_dir, options)


def _parse_pdf_with_markitdown_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise FileParseError(path.name, reason="MarkItDown is not available.") from exc

    logger.info("parse_pdf_markitdown_start", filename=path.name, parser_parallelism=options.parser_parallelism)
    result = MarkItDown().convert(str(path))
    if not result.text_content or not result.text_content.strip():
        raise FileParseError(path.name, reason="MarkItDown returned empty markdown.")
    return result.text_content


__all__ = ["parse_pdf_with_markitdown"]
