"""Ingest 解析器公共工具函数。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import structlog

logger = structlog.get_logger()

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def save_image_bytes(data: bytes, asset_dir: Path, name_hint: str, ext: str = ".png") -> str:
    """把图片字节写入 asset_dir，返回相对文件名。"""
    content_hash = hashlib.md5(data).hexdigest()[:10]
    safe_hint = re.sub(r"[^\w\-]", "_", name_hint)[:40]
    filename = f"{safe_hint}_{content_hash}{ext}"
    out_path = asset_dir / filename
    out_path.write_bytes(data)
    return filename
