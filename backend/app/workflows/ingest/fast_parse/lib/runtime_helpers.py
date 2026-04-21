"""Shared ingest runtime helpers used by parse/finalize/enhance nodes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import mimetypes
import re
from pathlib import Path

from app.models import RawFileAsset

try:
    from PIL import Image
except ImportError:
    Image = None

_PAGE_RE = re.compile(r"(?:page|p|slide|s)[_\-]?(\d{1,4})", re.IGNORECASE)

# Track background tasks to prevent GC collection (RISK-2 fix)
_background_tasks: set[asyncio.Task] = set()


@dataclass(frozen=True, slots=True)
class _MinerUFastParseResult:
    markdown: str
    parser_used: str
    attempted_parsers: list[str]
    parser_elapsed_s: dict[str, float]
    rewritten_image_refs: int
    extracted_data_images: int
    appended_asset_images: int
    needs_enhance: bool
    needs_quality_reparse: bool = False
    needs_asset_ocr: bool = False
def _guess_asset_kind(filename: str) -> str:
    lowered = filename.lower()
    if "formula" in lowered or "equation" in lowered or "latex" in lowered:
        return "formula_image"
    return "image"


def _guess_page_num(filename: str) -> int | None:
    match = _PAGE_RE.search(filename)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _compute_quality_score(*, markdown: str, image_count: int, classification: dict[str, object]) -> float:
    score = 0.55
    if markdown.strip():
        score += 0.2
    if len(markdown.strip()) >= 500:
        score += 0.1
    if image_count > 0:
        score += 0.05
    if classification.get("has_tables"):
        score += 0.05
    if classification.get("has_formulas"):
        score += 0.05
    return max(0.0, min(round(score, 3), 1.0))
def _read_image_dimensions(path: Path) -> tuple[int | None, int | None]:
    if Image is None:
        return None, None
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except Exception:
        return None, None


def _build_asset_rows(
    *,
    raw_file_id: int,
    asset_dir: Path,
    asset_storage_dir: str,
    storage_backend: str,
) -> list[RawFileAsset]:
    rows: list[RawFileAsset] = []
    normalized_storage_dir = asset_storage_dir.rstrip("/")
    for path in sorted(asset_dir.iterdir()):
        if not path.is_file():
            continue
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        width, height = _read_image_dimensions(path)
        rows.append(
            RawFileAsset(
                raw_file_id=raw_file_id,
                asset_name=path.name,
                asset_kind=_guess_asset_kind(path.name),
                storage_backend=storage_backend,
                storage_key=f"{normalized_storage_dir}/{path.name}",
                mime_type=mime_type,
                page_num=_guess_page_num(path.name),
                width=width,
                height=height,
                ocr_text=None,
            )
        )
    return rows
