"""Shared utilities for ingest parser implementations."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


MIME_MAP: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def save_image_bytes(
    data: bytes,
    asset_dir: Path,
    name_hint: str,
    ext: str = ".png",
    name_prefix: str = "",
) -> str:
    """Write image bytes into the asset directory and return the relative name."""

    content_hash = hashlib.md5(data).hexdigest()[:10]
    safe_hint = re.sub(r"[^\w\-]", "_", name_hint)[:40]
    safe_prefix = re.sub(r"[^\w\-]+", "_", name_prefix).strip("_")
    normalized_ext = ext if ext.startswith(".") else f".{ext}"
    filename = (
        f"{safe_prefix}__{safe_hint}_{content_hash}{normalized_ext}"
        if safe_prefix
        else f"{safe_hint}_{content_hash}{normalized_ext}"
    )
    path = asset_dir / filename
    if not path.exists():
        path.write_bytes(data)
    return filename
