"""Authoritative upload type whitelist used by ingest intake."""

from __future__ import annotations

# 当前产品入口真正开放的 ingest 文件类型白名单。
# 图片只允许走 PaddleOCR / MinerU 外部解析链路，不提供本地兜底。
SUPPORTED_UPLOAD_EXTENSIONS: tuple[str, ...] = (
    ".txt",
    ".docx",
    ".pptx",
    ".pdf",
    ".md",
    ".jpeg",
    ".jpg",
    ".png",
    ".bmp",
)

SUPPORTED_UPLOAD_EXTENSION_SET = frozenset(SUPPORTED_UPLOAD_EXTENSIONS)


__all__ = [
    "SUPPORTED_UPLOAD_EXTENSIONS",
    "SUPPORTED_UPLOAD_EXTENSION_SET",
]
