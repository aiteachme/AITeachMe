"""Asset indexing for digest builds."""

from __future__ import annotations

import structlog

from app.shared.infra.storage import get_content_store, run_store_sync
from app.workflows.digest.common.models import AssetItem, AssetRegistry, SourcePacket

logger = structlog.get_logger()


def build_asset_registry(course_id: str, source_packets: list[SourcePacket]) -> AssetRegistry:
    """Index markdown-referenced assets once for the selected source files."""

    if not source_packets:
        return AssetRegistry(course_id=course_id, asset_dir="")

    cs = get_content_store()
    asset_dir = source_packets[0].asset_dir
    assets: list[AssetItem] = []
    missing_assets = 0
    sizes_by_prefix: dict[str, dict[str, int]] = {}

    for packet in source_packets:
        if not packet.image_refs:
            continue
        prefix = packet.asset_dir.rstrip("/") + "/"
        if prefix not in sizes_by_prefix:
            sizes_by_prefix[prefix] = run_store_sync(cs.list_prefix_sizes, prefix, default={}) or {}
        stored_sizes = sizes_by_prefix[prefix]
        key_by_name = {key.rsplit("/", 1)[-1]: key for key in stored_sizes}
        for asset_name in dict.fromkeys(packet.image_refs):
            asset_key = key_by_name.get(asset_name)
            asset_exists = bool(asset_key)
            if not asset_exists:
                missing_assets += 1
            assets.append(
                AssetItem(
                    filename=asset_name,
                    file_id=packet.file_id,
                    page_number=_extract_page_number(asset_name),
                    asset_type=_detect_asset_type(asset_name),
                    file_size=stored_sizes.get(asset_key or "", 0),
                    ocr_available=asset_exists,
                )
            )

    registry = AssetRegistry(course_id=course_id, asset_dir=asset_dir, assets=assets)
    logger.info(
        "asset_registry_built",
        course_id=course_id,
        asset_count=len(assets),
        missing_asset_count=missing_assets,
    )
    return registry


def _detect_asset_type(filename: str) -> str:
    lowered = filename.lower()
    if "fallback" in lowered or "page" in lowered:
        return "fallback"
    if "draw" in lowered or "diagram" in lowered:
        return "drawing"
    return "image"


def _extract_page_number(filename: str) -> int | None:
    digits = []
    lowered = filename.lower()
    marker_index = lowered.find("_p")
    if marker_index >= 0:
        for char in lowered[marker_index + 2:]:
            if char.isdigit():
                digits.append(char)
            else:
                break
    if not digits:
        return None
    return int("".join(digits))
