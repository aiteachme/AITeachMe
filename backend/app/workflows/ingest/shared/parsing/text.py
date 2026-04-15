"""Plain-text parsing helpers used by the ingest workflow."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.shared.infra.exceptions import FileParseError
from app.workflows.ingest.shared.parsing.formats import (
    get_text_language_hint,
    is_markdown_extension,
    is_prose_text_extension,
)
from app.workflows.ingest.shared.parsing.types import ParserRunOptions


TEXT_NATIVE_AVAILABLE = True
TEXT_FALLBACK_EXTENSION = ".txt"
_TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "gb18030", "latin-1")
_MAX_TEXT_PROBE_BYTES = 64 * 1024
_DISALLOWED_CONTROL_BYTES = frozenset(set(range(0x00, 0x20)) - {0x09, 0x0A, 0x0D})
_BACKTICK_RUN_RE = re.compile(r"`{3,}")


async def parse_text_with_native(
    file_path: str | Path,
    asset_dir: Path,
    options: ParserRunOptions,
) -> str:
    """Read a text-like file directly and normalize it into markdown."""

    del asset_dir
    del options
    path = Path(file_path)
    text = await asyncio.to_thread(_read_text_file, path)
    return render_text_file_as_markdown(path, text)


def read_text_file(file_path: str | Path) -> str:
    """Read a text-like file with a small encoding fallback chain."""

    return _read_text_file(Path(file_path))


def is_probably_text_file(file_path: str | Path) -> bool:
    """Heuristically detect whether a file is text-decodable."""

    path = Path(file_path)
    try:
        raw = path.read_bytes()[:_MAX_TEXT_PROBE_BYTES]
    except OSError:
        return False

    if not raw:
        return True
    if b"\x00" in raw:
        return False

    control_count = sum(byte in _DISALLOWED_CONTROL_BYTES for byte in raw)
    if control_count / max(len(raw), 1) > 0.02:
        return False

    for encoding in _TEXT_ENCODINGS:
        try:
            raw.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def render_text_file_as_markdown(path: Path, text: str) -> str:
    """Preserve structured text safely when converting it into markdown."""

    if not text.strip():
        return f"_Empty file: {path.name}_\n"

    extension = path.suffix.lower()
    if is_markdown_extension(extension) or is_prose_text_extension(extension):
        return text

    language = get_text_language_hint(extension)
    return _wrap_in_fenced_block(text, language=language)


def _read_text_file(path: Path) -> str:
    for encoding in _TEXT_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise FileParseError(path.name, reason="Text decoding failed with all known encodings.")


def _wrap_in_fenced_block(text: str, *, language: str | None) -> str:
    fence = _choose_fence(text)
    suffix = language or ""
    return f"{fence}{suffix}\n{text.rstrip()}\n{fence}\n"


def _choose_fence(text: str) -> str:
    longest_run = max((len(match.group(0)) for match in _BACKTICK_RUN_RE.finditer(text)), default=2)
    return "`" * max(longest_run + 1, 3)
