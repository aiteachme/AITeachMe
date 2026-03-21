"""Plain text and markdown parsers used by the ingest workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.exceptions import FileParseError
from app.workflows.ingest.parsing.types import ParserRunOptions


TEXT_NATIVE_AVAILABLE = True
_TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "gb18030", "latin-1")


async def parse_text_with_native(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Read a markdown or plain-text file directly from disk."""

    del asset_dir
    del options
    return await asyncio.to_thread(_read_text_file, Path(file_path))


def read_text_file(file_path: str | Path) -> str:
    """Read a text file with a small encoding fallback chain."""

    return _read_text_file(Path(file_path))


def _read_text_file(path: Path) -> str:
    decoded_empty = False
    for encoding in _TEXT_ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        if text.strip():
            return text
        decoded_empty = True
        break
    if decoded_empty:
        raise FileParseError(path.name, reason="Text file is empty.")
    raise FileParseError(path.name, reason="Text decoding failed with all known encodings.")
