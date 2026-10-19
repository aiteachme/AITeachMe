"""Load only strictly recommended, chapter-relevant original images for Writer."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.shared.infra.storage import get_content_store
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.docgen_multimodal.lib.chapter_visual_context import visual_source_url
from app.workflows.digest.docgen_multimodal.lib.models import VisualEvidence, WriterRereadImage
from app.workflows.digest.docgen_multimodal.lib.visual_evidence import _prepare_image_bytes

_MAX_REREAD_IMAGE_EDGE = 1600
_MAX_RAW_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_PREPARED_IMAGE_BYTES = 6 * 1024 * 1024


@dataclass
class WriterImageLoadResult:
    images: list[WriterRereadImage] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)


async def load_writer_reread_images(
    *,
    material_context: DigestMaterialContext,
    visual_evidence: Sequence[VisualEvidence],
    chapter_plan: Mapping[str, Any],
    digest_mode: str,
) -> WriterImageLoadResult:
    """Resolve bounded assets within the selected file prefixes; no LLM calls."""

    result = WriterImageLoadResult()
    source_urls = {
        str(item.get("url") or "")
        for item in chapter_plan.get("source_details") or []
        if isinstance(item, Mapping)
    }
    relevance = {
        (item.get("file_id"), item.get("section_ref")): float(item.get("relevance") or 0)
        for item in chapter_plan.get("source_slices") or []
        if isinstance(item, Mapping)
    }
    candidates = [
        item for item in visual_evidence
        if item.can_reread
        and (item.file_id, item.section_ref) in relevance
        and visual_source_url(item) in source_urls
    ]
    if not candidates:
        return result

    candidates.sort(key=lambda item: (
        -relevance.get((item.file_id, item.section_ref), 0),
        -item.teaching_value,
        -item.confidence,
        item.image_id,
    ))
    packets = {item.file_id: item for item in material_context.source_packets}
    sections = {
        (item.source_file_id, item.digest_chunk_uid)
        for item in material_context.section_packets
    }
    store = get_content_store()
    keys_by_prefix: dict[str, list[str]] = {}
    seen_hashes: set[str] = set()
    prepared_bytes = 0
    limit = 2

    for item in candidates:
        if len(result.images) >= limit:
            break
        if item.image_sha256 in seen_hashes:
            continue
        packet = packets.get(item.file_id)
        if packet is None or (item.file_id, item.section_ref) not in sections:
            continue
        filename = item.asset_filename
        if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
            result.failures.append({"image_id": item.image_id, "reason": "invalid_asset_filename"})
            continue
        prefix = packet.asset_dir.rstrip("/") + "/"
        if not packet.asset_dir.strip():
            continue
        try:
            if prefix not in keys_by_prefix:
                keys_by_prefix[prefix] = await store.list_prefix(prefix)
            matches = [
                key for key in keys_by_prefix[prefix]
                if key.startswith(prefix)
                and ".." not in key[len(prefix):].replace("\\", "/").split("/")
                and key.rsplit("/", 1)[-1].casefold() == filename.casefold()
            ]
            if len(matches) != 1:
                result.failures.append({"image_id": item.image_id, "reason": "missing_or_ambiguous_asset"})
                continue
            raw = await store.read_bytes(matches[0])
            if len(raw) > _MAX_RAW_IMAGE_BYTES:
                result.failures.append({"image_id": item.image_id, "reason": "image_too_large"})
                continue
            data_url, _width, _height, _mime, size, sha256 = await asyncio.to_thread(
                _prepare_image_bytes, raw, source_name=filename, max_edge=_MAX_REREAD_IMAGE_EDGE
            )
            if sha256 != item.image_sha256:
                result.failures.append({"image_id": item.image_id, "reason": "image_changed_since_understanding"})
                continue
            if prepared_bytes + size > _MAX_PREPARED_IMAGE_BYTES:
                result.failures.append({"image_id": item.image_id, "reason": "image_byte_budget_exceeded"})
                continue
            result.images.append(WriterRereadImage(
                image_id=item.image_id,
                file_id=item.file_id,
                section_ref=item.section_ref,
                asset_filename=filename,
                summary=item.summary,
                reread_reason=item.reread_reason,
                prepared_bytes=size,
                data_url=data_url,
            ))
            prepared_bytes += size
            seen_hashes.add(sha256)
        except Exception as exc:
            result.failures.append({"image_id": item.image_id, "reason": type(exc).__name__})
    return result


__all__ = ["WriterImageLoadResult", "load_writer_reread_images"]
