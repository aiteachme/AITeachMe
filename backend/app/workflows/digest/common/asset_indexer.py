"""Asset indexing for digest builds."""

from __future__ import annotations

from pathlib import Path

import structlog

from app.workflows.digest.common.models import AssetItem, AssetRegistry, SourcePacket

logger = structlog.get_logger()


def build_asset_registry(subject: str, source_packets: list[SourcePacket]) -> AssetRegistry:
    """Index markdown-referenced assets once for the selected source files."""

    if not source_packets:
        return AssetRegistry(subject=subject, asset_dir="")

    asset_dir = source_packets[0].asset_dir
    assets: list[AssetItem] = []
    missing_assets = 0

    for packet in source_packets:
        packet_asset_dir = Path(packet.asset_dir)
        for asset_name in dict.fromkeys(packet.image_refs):
            asset_path = packet_asset_dir / asset_name
            asset_exists = asset_path.exists() and asset_path.is_file()
            if not asset_exists:
                missing_assets += 1
            assets.append(
                AssetItem(
                    filename=asset_name,
                    file_id=packet.file_id,
                    page_number=_extract_page_number(asset_name),
                    asset_type=_detect_asset_type(asset_name),
                    file_size=asset_path.stat().st_size if asset_exists else 0,
                    ocr_available=asset_exists,
                )
            )

    registry = AssetRegistry(subject=subject, asset_dir=asset_dir, assets=assets)
    logger.info(
        "asset_registry_built",
        subject=subject,
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

