"""
文件类型路由 + Markdown Pretty Printer

根据文件扩展名路由到正确的解析器，未知格式抛出 UnsupportedFileTypeError。
Pretty_Printer 对 Markdown 进行规范化（去除多余空行、统一换行）。
"""

from __future__ import annotations

import re
from pathlib import Path

import structlog

from app.core.exceptions import UnsupportedFileTypeError
from app.agents.ingest.parsers import parse_pdf, parse_pptx, parse_docx, parse_image

logger = structlog.get_logger()

# 扩展名 → 解析器映射
_PARSER_MAP: dict[str, callable] = {
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
    """根据文件扩展名路由到对应解析器，返回 Markdown 文本。

    Args:
        file_path: 文件路径。

    Returns:
        规范化后的 Markdown 文本。

    Raises:
        UnsupportedFileTypeError: 不支持的文件格式。
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    parser = _PARSER_MAP.get(ext)
    if parser is None:
        raise UnsupportedFileTypeError(ext)

    logger.info("parse_file_routing", file=file_path.name, ext=ext)
    raw_markdown = await parser(file_path)
    return pretty_print(raw_markdown)


def pretty_print(markdown: str) -> str:
    """Markdown 规范化：去除多余空行、修剪尾部空白、确保文件末尾换行。"""
    if not markdown:
        return ""

    lines = markdown.splitlines()

    # 去除每行尾部空白
    lines = [line.rstrip() for line in lines]

    # 合并连续空行为最多一个空行
    result: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank

    # 去除首尾空行
    while result and result[0] == "":
        result.pop(0)
    while result and result[-1] == "":
        result.pop()

    text = "\n".join(result)
    # 确保文件末尾有换行
    if text and not text.endswith("\n"):
        text += "\n"
    return text
