"""文件解析编排器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
import time

import structlog

from app.agents.ingest.parsers import parse_docx, parse_image, parse_pdf, parse_pptx
from app.core.exceptions import UnsupportedFileTypeError

logger = structlog.get_logger()

Parser = Callable[[str | Path, Path], Awaitable[str]]

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


async def parse_file(file_path: str | Path, asset_dir: str | Path) -> str:
    """按扩展名选择解析器并返回规范化 Markdown。

    Args:
        file_path: 原始文件路径。
        asset_dir: 提取的图片等资源保存目录。
    """
    path = Path(file_path)
    assets = Path(asset_dir)
    assets.mkdir(parents=True, exist_ok=True)

    parser = _PARSER_MAP.get(path.suffix.lower())
    if parser is None:
        raise UnsupportedFileTypeError(path.suffix.lower())

    started_at = time.monotonic()
    logger.info(
        "parse_file_routing",
        filename=path.name,
        extension=path.suffix.lower(),
        parser=parser.__name__,
    )
    markdown = await parser(path, assets)
    from app.agents.ingest.canonicalizer import canonicalize_markdown
    pretty_markdown = canonicalize_markdown(markdown)
    elapsed = round(time.monotonic() - started_at, 2)

    # 统计提取的图片数
    image_count = len(list(assets.glob("*"))) if assets.exists() else 0

    logger.info(
        "parse_file_completed",
        filename=path.name,
        parser=parser.__name__,
        raw_chars=len(markdown),
        final_chars=len(pretty_markdown),
        images_extracted=image_count,
        elapsed_s=elapsed,
    )
    return pretty_markdown
