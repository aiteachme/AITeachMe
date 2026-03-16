"""文件解析编排器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog

from app.agents.ingest.parsers import parse_docx, parse_image, parse_pdf, parse_pptx
from app.core.exceptions import UnsupportedFileTypeError

logger = structlog.get_logger()

Parser = Callable[[str | Path], Awaitable[str]]

_PARSER_MAP: dict[str, Parser] = {
    ".pdf": parse_pdf,
    ".ppt": parse_pptx,
    ".pptx": parse_pptx,
    ".docx": parse_docx,
    ".png": parse_image,
    ".jpg": parse_image,
    ".jpeg": parse_image,
    ".webp": parse_image,
}

SUPPORTED_EXTENSIONS = frozenset(_PARSER_MAP.keys())


async def parse_file(file_path: str | Path) -> str:
    """按扩展名选择解析器并返回规范化 Markdown。"""

    path = Path(file_path)
    parser = _PARSER_MAP.get(path.suffix.lower())
    if parser is None:
        raise UnsupportedFileTypeError(path.suffix.lower())

    logger.info("parse_file_routing", filename=path.name, extension=path.suffix.lower())
    markdown = await parser(path)
    return pretty_print(markdown)


def pretty_print(markdown: str) -> str:
    """对 Markdown 做轻量格式规范化。"""

    if not markdown:
        return ""

    lines = [line.rstrip() for line in markdown.splitlines()]
    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and previous_blank:
            continue
        cleaned.append(line)
        previous_blank = is_blank

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    text = "\n".join(cleaned)
    if text and not text.endswith("\n"):
        text += "\n"
    return text
