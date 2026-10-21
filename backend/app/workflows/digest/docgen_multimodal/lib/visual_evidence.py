"""Source-image discovery, preparation, caching, and visual understanding."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import structlog
from PIL import Image, ImageOps

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.shared.infra.settings import get_settings
from app.shared.infra.storage import get_content_store, resolve_course_storage_scope
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen_multimodal.lib.model_policy import (
    MultimodalDocGenModelStep,
    multimodal_docgen_completion_kwargs_with_metadata,
)
from app.workflows.digest.docgen_multimodal.lib.models import (
    MaterialImageOccurrence,
    VisualEvidence,
    VisualEvidenceBatchResponse,
    VisualEvidenceCacheEntry,
    VisualEvidenceDecision,
)
from app.workflows.digest.docgen_multimodal.prompts.visual_evidence import (
    VISUAL_EVIDENCE_DETAIL,
    VISUAL_EVIDENCE_PROMPT_VERSION,
    build_visual_evidence_messages,
)

logger = structlog.get_logger(__name__)

_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
_HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*?\bsrc=[\"'](?P<target>[^\"']+)[\"'][^>]*?(?:\balt=[\"'](?P<alt>[^\"']*)[\"'])?[^>]*>",
    re.IGNORECASE,
)
_REMOTE_SCHEMES = {"http", "https", "data"}
_CONTEXT_RADIUS_CHARS = 900
_DEFAULT_MAX_IMAGE_EDGE = 1600
_DEFAULT_IMAGES_PER_BATCH = 4
_VISUAL_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VisualEvidenceFailure:
    image_id: str
    file_id: str
    section_ref: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "image_id": self.image_id,
            "file_id": self.file_id,
            "section_ref": self.section_ref,
            "reason": self.reason,
        }


@dataclass
class VisualEvidenceRunResult:
    evidence: list[VisualEvidence] = field(default_factory=list)
    failures: list[VisualEvidenceFailure] = field(default_factory=list)
    discovered_count: int = 0
    meaningful_count: int = 0
    meaningless_count: int = 0
    cache_hit_count: int = 0
    llm_call_count: int = 0
    prepared_image_bytes: int = 0

    def metrics(self) -> dict[str, int | str]:
        return {
            "discovered_image_count": self.discovered_count,
            "meaningful_image_count": self.meaningful_count,
            "reread_recommended_image_count": sum(item.reread_recommended for item in self.evidence),
            "meaningless_image_count": self.meaningless_count,
            "visual_evidence_failure_count": len(self.failures),
            "visual_evidence_cache_hit_count": self.cache_hit_count,
            "visual_evidence_llm_call_count": self.llm_call_count,
            "prepared_image_bytes": self.prepared_image_bytes,
            "detail": VISUAL_EVIDENCE_DETAIL,
            "prompt_version": VISUAL_EVIDENCE_PROMPT_VERSION,
        }


@dataclass(frozen=True)
class _ImageMatch:
    start: int
    end: int
    target: str
    alt_text: str


@dataclass(frozen=True)
class _BatchResult:
    decisions: dict[str, VisualEvidenceDecision]
    failures: list[VisualEvidenceFailure]


def _ordered_image_matches(markdown: str) -> list[_ImageMatch]:
    matches: list[_ImageMatch] = []
    for pattern in (_MARKDOWN_IMAGE_RE, _HTML_IMAGE_RE):
        for match in pattern.finditer(markdown):
            matches.append(
                _ImageMatch(
                    start=match.start(),
                    end=match.end(),
                    target=str(match.groupdict().get("target") or "").strip(),
                    alt_text=str(match.groupdict().get("alt") or "").strip(),
                )
            )
    return sorted(matches, key=lambda item: (item.start, item.end))


def _target_path(raw_target: str) -> str:
    value = str(raw_target or "").strip().strip("<>")
    if not value:
        return ""
    if " " in value:
        value = value.split(" ", 1)[0]
    parsed = urlsplit(value)
    if parsed.scheme.lower() in _REMOTE_SCHEMES:
        return ""
    return unquote(parsed.path or value).replace("\\", "/")


def _asset_name(raw_target: str) -> str:
    path = _target_path(raw_target)
    if not path:
        return ""
    return path.rsplit("/", 1)[-1].strip()


def _nearby_text(markdown: str, match: _ImageMatch) -> str:
    start = max(0, match.start - _CONTEXT_RADIUS_CHARS)
    end = min(len(markdown), match.end + _CONTEXT_RADIUS_CHARS)
    before = markdown[start:match.start].strip()
    after = markdown[match.end:end].strip()
    return "\n\n".join(item for item in [before, after] if item).strip()


def _mime_for_format(image_format: str | None) -> str:
    normalized = str(image_format or "").upper()
    if normalized == "PNG":
        return "image/png"
    if normalized == "WEBP":
        return "image/webp"
    return "image/jpeg"


def _prepare_image_bytes(
    raw: bytes,
    *,
    source_name: str,
    max_edge: int,
) -> tuple[str, int, int, str, int, str]:
    """Return data URL, dimensions, MIME, prepared size, and raw SHA256."""

    if len(raw) < 100:
        raise ValueError("image_bytes_too_small")
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    with Image.open(io.BytesIO(raw)) as opened:
        try:
            opened.seek(0)
        except EOFError:
            pass
        image = ImageOps.exif_transpose(opened)
        if image.width <= 0 or image.height <= 0:
            raise ValueError("invalid_image_dimensions")
        image.thumbnail((max(64, int(max_edge)), max(64, int(max_edge))), Image.Resampling.LANCZOS)
        width, height = image.size
        extension = Path(source_name).suffix.lower()
        preserve_png = extension == ".png" or "A" in image.getbands()
        output = io.BytesIO()
        if preserve_png:
            if image.mode not in {"RGB", "RGBA", "L", "LA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image.save(output, format="PNG", optimize=True)
            image_format = "PNG"
        else:
            if image.mode != "RGB":
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            image.save(output, format="JPEG", quality=90, optimize=True)
            image_format = "JPEG"
    prepared = output.getvalue()
    mime_type = _mime_for_format(image_format)
    encoded = base64.b64encode(prepared).decode("ascii")
    return (
        f"data:{mime_type};base64,{encoded}",
        width,
        height,
        mime_type,
        len(prepared),
        raw_sha256,
    )


def _image_id(
    *,
    file_id: str,
    section_ref: str,
    occurrence_index: int,
    asset_filename: str,
    image_sha256: str,
) -> str:
    identity = "\0".join(
        [file_id, section_ref, str(occurrence_index), asset_filename, image_sha256]
    )
    return f"img_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def _sections_by_file(material_context: DigestMaterialContext) -> dict[str, list[SectionPacket]]:
    grouped: dict[str, list[SectionPacket]] = {}
    for section in list(material_context.section_packets or []):
        grouped.setdefault(section.source_file_id, []).append(section)
    return grouped


async def collect_material_image_occurrences(
    material_context: DigestMaterialContext,
    *,
    max_image_edge: int = _DEFAULT_MAX_IMAGE_EDGE,
) -> tuple[list[MaterialImageOccurrence], list[VisualEvidenceFailure]]:
    """Resolve ordered Markdown image occurrences to safe ContentStore assets."""

    store = get_content_store()
    grouped_sections = _sections_by_file(material_context)
    occurrences: list[MaterialImageOccurrence] = []
    failures: list[VisualEvidenceFailure] = []
    prepared_by_asset_key: dict[str, tuple[str, int, int, str, int, str]] = {}

    for packet in list(material_context.source_packets or []):
        prefix = packet.asset_dir.rstrip("/") + "/"
        try:
            stored_keys = await store.list_prefix(prefix)
        except Exception as exc:
            logger.warning(
                "docgen_multimodal_asset_list_failed",
                file_id=packet.file_id,
                asset_prefix=prefix,
                error=str(exc),
            )
            stored_keys = []
        keys_by_name: dict[str, list[str]] = {}
        for key in stored_keys:
            keys_by_name.setdefault(key.rsplit("/", 1)[-1].casefold(), []).append(key)

        for section in grouped_sections.get(packet.file_id, []):
            markdown = str(section.normalized_content or "")
            for occurrence_index, match in enumerate(_ordered_image_matches(markdown), start=1):
                asset_filename = _asset_name(match.target)
                provisional_id = _image_id(
                    file_id=packet.file_id,
                    section_ref=section.digest_chunk_uid,
                    occurrence_index=occurrence_index,
                    asset_filename=asset_filename or "missing",
                    image_sha256="unresolved",
                )
                if not asset_filename:
                    failures.append(
                        VisualEvidenceFailure(
                            image_id=provisional_id,
                            file_id=packet.file_id,
                            section_ref=section.digest_chunk_uid,
                            reason="unsupported_or_remote_image_target",
                        )
                    )
                    continue
                candidate_keys = keys_by_name.get(asset_filename.casefold(), [])
                if len(candidate_keys) != 1:
                    failures.append(
                        VisualEvidenceFailure(
                            image_id=provisional_id,
                            file_id=packet.file_id,
                            section_ref=section.digest_chunk_uid,
                            reason="missing_asset" if not candidate_keys else "ambiguous_asset_name",
                        )
                    )
                    continue
                asset_key = candidate_keys[0]
                prepared = prepared_by_asset_key.get(asset_key)
                if prepared is None:
                    try:
                        raw = await store.read_bytes(asset_key)
                        prepared = await asyncio.to_thread(
                            _prepare_image_bytes,
                            raw,
                            source_name=asset_filename,
                            max_edge=max_image_edge,
                        )
                        prepared_by_asset_key[asset_key] = prepared
                    except Exception as exc:
                        failures.append(
                            VisualEvidenceFailure(
                                image_id=provisional_id,
                                file_id=packet.file_id,
                                section_ref=section.digest_chunk_uid,
                                reason=f"invalid_or_unreadable_asset:{type(exc).__name__}",
                            )
                        )
                        continue
                data_url, width, height, mime_type, prepared_size, image_sha256 = prepared
                nearby_text = _nearby_text(markdown, match)
                context_sha256 = hashlib.sha256(
                    (markdown + "\0" + nearby_text).encode("utf-8")
                ).hexdigest()
                occurrences.append(
                    MaterialImageOccurrence(
                        image_id=_image_id(
                            file_id=packet.file_id,
                            section_ref=section.digest_chunk_uid,
                            occurrence_index=occurrence_index,
                            asset_filename=asset_filename,
                            image_sha256=image_sha256,
                        ),
                        file_id=packet.file_id,
                        source_filename=packet.filename,
                        section_ref=section.digest_chunk_uid,
                        section_title=section.title or section.header_path,
                        occurrence_index=occurrence_index,
                        markdown_target=match.target,
                        asset_key=asset_key,
                        asset_filename=asset_filename,
                        alt_text=match.alt_text,
                        nearby_text=nearby_text,
                        section_text=markdown,
                        page_number=section.page_num,
                        mime_type=mime_type,
                        file_size=prepared_size,
                        width=width,
                        height=height,
                        sha256=image_sha256,
                        context_sha256=context_sha256,
                        data_url=data_url,
                    )
                )
    return occurrences, failures


def visual_evidence_cache_key(
    occurrence: MaterialImageOccurrence,
    *,
    model_identity: str,
) -> str:
    payload = "\0".join(
        [
            str(_VISUAL_CACHE_SCHEMA_VERSION),
            occurrence.sha256,
            occurrence.context_sha256,
            model_identity,
            VISUAL_EVIDENCE_PROMPT_VERSION,
            VISUAL_EVIDENCE_DETAIL,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_prefix(course_id: str) -> str:
    scope = resolve_course_storage_scope(course_id)
    return (
        f"{scope.namespace}/cache/docgen_multimodal/visual_evidence/"
        f"{VISUAL_EVIDENCE_PROMPT_VERSION}/"
    )


def _cache_path(prefix: str, cache_key: str) -> str:
    return f"{prefix}{cache_key}.json"


async def _read_cached_decision(
    occurrence: MaterialImageOccurrence,
    *,
    cache_prefix: str,
    cache_key: str,
    model_identity: str,
) -> VisualEvidenceDecision | None:
    store = get_content_store()
    entry = await store.read_json(
        _cache_path(cache_prefix, cache_key),
        VisualEvidenceCacheEntry,
    )
    if entry is None:
        return None
    if (
        entry.cache_key != cache_key
        or entry.image_sha256 != occurrence.sha256
        or entry.context_sha256 != occurrence.context_sha256
        or entry.model != model_identity
        or entry.prompt_version != VISUAL_EVIDENCE_PROMPT_VERSION
        or entry.detail != VISUAL_EVIDENCE_DETAIL
    ):
        return None
    # image_id identifies one Markdown occurrence, while the cached semantic
    # decision is reusable when identical image bytes appear in the same
    # context under a different occurrence ID.
    return entry.decision.model_copy(update={"image_id": occurrence.image_id})


async def _write_cached_decision(
    occurrence: MaterialImageOccurrence,
    decision: VisualEvidenceDecision,
    *,
    cache_prefix: str,
    cache_key: str,
    model_identity: str,
) -> None:
    entry = VisualEvidenceCacheEntry(
        cache_key=cache_key,
        image_sha256=occurrence.sha256,
        context_sha256=occurrence.context_sha256,
        model=model_identity,
        prompt_version=VISUAL_EVIDENCE_PROMPT_VERSION,
        decision=decision,
        created_at=datetime.now(UTC),
    )
    try:
        await get_content_store().write_json(_cache_path(cache_prefix, cache_key), entry)
    except Exception as exc:
        logger.warning(
            "docgen_multimodal_visual_cache_write_failed",
            image_id=occurrence.image_id,
            error=str(exc),
        )


def _chunks(items: Sequence[MaterialImageOccurrence], size: int) -> list[list[MaterialImageOccurrence]]:
    bounded_size = max(1, int(size))
    return [list(items[index : index + bounded_size]) for index in range(0, len(items), bounded_size)]


async def _understand_batch(
    batch: list[MaterialImageOccurrence],
    *,
    model_name: str,
    extra_metadata: dict[str, Any],
) -> _BatchResult:
    expected = {item.image_id: item for item in batch}
    try:
        response = await acompletion_with_fallback(
            build_visual_evidence_messages(batch),
            response_model=VisualEvidenceBatchResponse,
            **multimodal_docgen_completion_kwargs_with_metadata(
                MultimodalDocGenModelStep.VISUAL_EVIDENCE,
                model_name=model_name,
                extra_metadata=extra_metadata,
                image_ids=list(expected),
                image_count=len(batch),
                section_refs=list(dict.fromkeys(item.section_ref for item in batch)),
                image_detail=VISUAL_EVIDENCE_DETAIL,
                visual_prompt_version=VISUAL_EVIDENCE_PROMPT_VERSION,
            ),
        )
        parsed = (
            response
            if isinstance(response, VisualEvidenceBatchResponse)
            else VisualEvidenceBatchResponse.model_validate(response)
        )
    except Exception as exc:
        logger.warning(
            "docgen_multimodal_visual_batch_failed",
            image_ids=list(expected),
            error=str(exc),
        )
        return _BatchResult(
            decisions={},
            failures=[
                VisualEvidenceFailure(
                    image_id=item.image_id,
                    file_id=item.file_id,
                    section_ref=item.section_ref,
                    reason=f"visual_llm_failed:{type(exc).__name__}",
                )
                for item in batch
            ],
        )

    decisions: dict[str, VisualEvidenceDecision] = {}
    for decision in parsed.decisions:
        if decision.image_id not in expected or decision.image_id in decisions:
            continue
        decisions[decision.image_id] = decision
    failures = [
        VisualEvidenceFailure(
            image_id=item.image_id,
            file_id=item.file_id,
            section_ref=item.section_ref,
            reason="visual_llm_missing_decision",
        )
        for item in batch
        if item.image_id not in decisions
    ]
    return _BatchResult(decisions=decisions, failures=failures)


async def generate_visual_evidence(
    *,
    course_id: str,
    material_context: DigestMaterialContext,
    visual_model_name: str,
    extra_metadata: dict[str, Any] | None = None,
    max_images_per_batch: int = _DEFAULT_IMAGES_PER_BATCH,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> VisualEvidenceRunResult:
    """Generate cacheable evidence; meaningless images never enter evidence output."""

    result = VisualEvidenceRunResult()
    occurrences, discovery_failures = await collect_material_image_occurrences(material_context)
    result.discovered_count = len(occurrences) + len(discovery_failures)
    result.failures.extend(discovery_failures)
    result.prepared_image_bytes = sum(item.file_size for item in occurrences)
    if not occurrences:
        if on_progress is not None:
            await on_progress(result.discovered_count, result.discovered_count)
        return result

    settings = get_settings()
    configured_light_model = str(visual_model_name or settings.models.light or settings.models.primary or "").strip()
    model_identity = f"light|{configured_light_model}"
    try:
        cache_prefix = _cache_prefix(course_id)
    except Exception as exc:
        logger.warning(
            "docgen_multimodal_visual_cache_disabled",
            course_id=course_id,
            error=str(exc),
        )
        cache_prefix = ""

    occurrence_by_id = {item.image_id: item for item in occurrences}
    decisions: dict[str, VisualEvidenceDecision] = {}
    misses: list[MaterialImageOccurrence] = []
    cache_keys: dict[str, str] = {}
    for occurrence in occurrences:
        cache_key = visual_evidence_cache_key(occurrence, model_identity=model_identity)
        cache_keys[occurrence.image_id] = cache_key
        cached = (
            await _read_cached_decision(
                occurrence,
                cache_prefix=cache_prefix,
                cache_key=cache_key,
                model_identity=model_identity,
            )
            if cache_prefix
            else None
        )
        if cached is None:
            misses.append(occurrence)
            continue
        decisions[occurrence.image_id] = cached
        result.cache_hit_count += 1

    batches = _chunks(misses, max_images_per_batch)
    result.llm_call_count = len(batches)
    completed_count = len(discovery_failures) + result.cache_hit_count
    progress_lock = asyncio.Lock()
    if on_progress is not None:
        await on_progress(completed_count, result.discovered_count)

    async def run_batch(batch: list[MaterialImageOccurrence]) -> _BatchResult:
        nonlocal completed_count
        batch_result = await _understand_batch(
            batch,
            model_name=configured_light_model,
            extra_metadata={
                **dict(extra_metadata or {}),
                "course_id": course_id,
                "docgen_lane": "docgen_multimodal",
            },
        )
        async with progress_lock:
            completed_count += len(batch)
            if on_progress is not None:
                await on_progress(completed_count, result.discovered_count)
        return batch_result

    batch_results = await run_llm_tasks(batches, run_batch) if batches else []
    cache_writes: list[asyncio.Task[None]] = []
    for batch_result in batch_results:
        result.failures.extend(batch_result.failures)
        for image_id, decision in batch_result.decisions.items():
            occurrence = occurrence_by_id[image_id]
            decisions[image_id] = decision
            if cache_prefix:
                cache_writes.append(
                    asyncio.create_task(
                        _write_cached_decision(
                            occurrence,
                            decision,
                            cache_prefix=cache_prefix,
                            cache_key=cache_keys[image_id],
                            model_identity=model_identity,
                        )
                    )
                )
    if cache_writes:
        await asyncio.gather(*cache_writes)

    for occurrence in occurrences:
        decision = decisions.get(occurrence.image_id)
        if decision is None:
            continue
        evidence = decision.to_evidence(
            occurrence,
            model=model_identity,
            prompt_version=VISUAL_EVIDENCE_PROMPT_VERSION,
        )
        if evidence is None:
            result.meaningless_count += 1
            continue
        result.evidence.append(evidence)
        result.meaningful_count += 1
    return result


__all__ = [
    "VisualEvidenceFailure",
    "VisualEvidenceRunResult",
    "collect_material_image_occurrences",
    "generate_visual_evidence",
    "visual_evidence_cache_key",
]
