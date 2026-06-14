"""MarkItDown PPTX parser used by the active ingest local fallback.

This file only adapts PPTX files into Markdown through the local MarkItDown
package. Upload policy, parser routing, and final persistence stay in the
ingest workflow lane.
"""

from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path

import structlog

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.parsing.lib.types import ParserRunOptions

logger = structlog.get_logger()


async def parse_pptx_with_markitdown(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Parse PPTX through MarkItDown."""

    return await asyncio.to_thread(_parse_pptx_with_markitdown_sync, Path(file_path), asset_dir, options)


def _parse_pptx_with_markitdown_sync(path: Path, asset_dir: Path, options: ParserRunOptions) -> str:
    del asset_dir
    try:
        markitdown_module = import_module("markitdown")
        markitdown_converter = getattr(markitdown_module, "MarkItDown")
    except (AttributeError, ImportError) as exc:
        raise FileParseError(path.name, reason="MarkItDown is not available.") from exc

    logger.info("parse_pptx_markitdown_start", filename=path.name, parser_parallelism=options.parser_parallelism)
    result = markitdown_converter().convert(str(path))
    if not result.text_content or not result.text_content.strip():
        raise FileParseError(path.name, reason="MarkItDown returned empty markdown.")
    return result.text_content


__all__ = ["parse_pptx_with_markitdown"]
