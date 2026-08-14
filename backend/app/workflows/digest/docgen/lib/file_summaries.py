"""LLM-based semantic routing from parsed source sections to confirmed chapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib.model_policy import (
    DocGenModelStep,
    docgen_completion_kwargs_with_metadata,
)
from app.workflows.digest.docgen.lib.models import (
    ChapterSourceSlice,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    SourceAffinityByChapter,
    clean_string_list,
)
from app.workflows.digest.docgen.lib.source_slices import build_section_catalog_for_file
from app.workflows.digest.docgen.prompts.file_summaries import build_file_summary_messages

logger = structlog.get_logger(__name__)

_FILE_ROUTING_BATCH_CHARS = 60_000
_FILE_ROUTING_MAX_SECTIONS_PER_BATCH = 80


def _sections_for_file(sections: Sequence[SectionPacket], file_id: str) -> list[SectionPacket]:
    return [section for section in sections if section.source_file_id == file_id]


def _chapter_affinity_from_slices(slices: Sequence[ChapterSourceSlice]) -> dict[int, float]:
    affinity: dict[int, float] = {}
    for source_slice in slices:
        try:
            chapter_index = int(source_slice.chapter_index)
        except (TypeError, ValueError):
            continue
        if chapter_index <= 0:
            continue
        affinity[chapter_index] = max(
            float(affinity.get(chapter_index, 0.0)),
            float(source_slice.relevance or 0.0),
        )
    return affinity


def _slice_section_refs(
    slices: Sequence[ChapterSourceSlice],
    *,
    limit: int = 24,
) -> list[str]:
    return clean_string_list(
        [source_slice.section_ref for source_slice in slices if source_slice.section_ref],
        limit=limit,
    )


def _merge_chapter_slices(
    slices: Sequence[ChapterSourceSlice],
) -> list[ChapterSourceSlice]:
    """Deduplicate and retain a balanced set of sections across chapters."""

    deduped: dict[str, ChapterSourceSlice] = {}
    for source_slice in slices:
        if int(source_slice.chapter_index or 0) <= 0 or not source_slice.section_ref:
            continue
        key = f"{source_slice.chapter_index}:{source_slice.file_id}:{source_slice.section_ref}"
        existing = deduped.get(key)
        if existing is None or source_slice.relevance > existing.relevance:
            deduped[key] = source_slice

    slices_by_chapter: dict[int, list[ChapterSourceSlice]] = {}
    for source_slice in deduped.values():
        slices_by_chapter.setdefault(int(source_slice.chapter_index), []).append(source_slice)
    for chapter_slices in slices_by_chapter.values():
        chapter_slices.sort(
            key=lambda item: (-float(item.relevance or 0.0), item.section_ref)
        )

    chapter_indices = sorted(
        slices_by_chapter,
        key=lambda index: (-float(slices_by_chapter[index][0].relevance or 0.0), index),
    )
    balanced: list[ChapterSourceSlice] = []
    cursor = 0
    while True:
        added = False
        for chapter_index in chapter_indices:
            chapter_slices = slices_by_chapter[chapter_index]
            if cursor >= len(chapter_slices):
                continue
            balanced.append(chapter_slices[cursor])
            added = True
        if not added:
            break
        cursor += 1
    return balanced


@dataclass(frozen=True)
class _FileRoutingJob:
    packet: SourcePacket
    sections: list[SectionPacket]
    batch_index: int
    batch_count: int


@dataclass(frozen=True)
class _FileRoutingResult:
    file_id: str
    summary: FileMaterialSummary


def _routing_batches(sections: Sequence[SectionPacket]) -> list[list[SectionPacket]]:
    """Group complete parsed sections without clipping their text."""

    batches: list[list[SectionPacket]] = []
    current: list[SectionPacket] = []
    current_chars = 0
    for section in sorted(sections, key=lambda item: int(item.chunk_index or 0)):
        section_chars = len(str(section.normalized_content or ""))
        if current and (
            current_chars + section_chars > _FILE_ROUTING_BATCH_CHARS
            or len(current) >= _FILE_ROUTING_MAX_SECTIONS_PER_BATCH
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(section)
        current_chars += section_chars
    if current:
        batches.append(current)
    return batches


def _render_complete_sections(sections: Sequence[SectionPacket]) -> str:
    blocks: list[str] = []
    for section in sections:
        body = str(section.normalized_content or "").strip()
        if not body:
            continue
        blocks.append(
            "\n".join(
                [
                    f"## Section {section.digest_chunk_uid}",
                    f"Title: {section.title or section.header_path}",
                    f"Header path: {section.header_path}",
                    f"Page: {section.page_num or 'unknown'}",
                    "",
                    body,
                ]
            ).strip()
        )
    return "\n\n".join(blocks).strip()


def _chapter_contracts(chapters: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chapter_index": int(chapter.get("chapter_index", index) or index),
            "title": str(chapter.get("title") or chapter.get("resolved_title") or "").strip(),
            "objective": str(chapter.get("objective") or "").strip(),
            "required_elements": clean_string_list(chapter.get("required_elements"), limit=16),
        }
        for index, chapter in enumerate(chapters, start=1)
    ]


def _normalize_llm_summary(
    summary: FileMaterialSummary,
    *,
    packet: SourcePacket,
    sections: Sequence[SectionPacket],
) -> FileMaterialSummary:
    catalog_by_ref = {
        str(item.get("section_ref") or ""): item
        for item in build_section_catalog_for_file(
            packet,
            sections=list(sections),
            max_sections=max(1, len(sections)),
        )
    }
    normalized_slices: list[ChapterSourceSlice] = []
    seen: set[tuple[int, str]] = set()
    for item in list(summary.chapter_slices or []):
        section_ref = str(item.section_ref or "").strip()
        catalog_item = catalog_by_ref.get(section_ref)
        chapter_index = int(item.chapter_index or 0)
        if catalog_item is None or chapter_index <= 0 or (chapter_index, section_ref) in seen:
            continue
        seen.add((chapter_index, section_ref))
        normalized_slices.append(
            item.model_copy(
                update={
                    "file_id": packet.file_id,
                    "filename": packet.filename,
                    "section_title": item.section_title or str(catalog_item.get("title") or ""),
                    "header_path": item.header_path or str(catalog_item.get("header_path") or ""),
                    "line_start": item.line_start or catalog_item.get("line_start"),
                    "line_end": item.line_end or catalog_item.get("line_end"),
                }
            )
        )
    summary.file_id = packet.file_id
    summary.filename = packet.filename
    summary.chapter_slices = normalized_slices
    summary.high_value_sections = clean_string_list(
        [*summary.high_value_sections, *[item.section_ref for item in normalized_slices]],
        limit=64,
    )
    summary.chapter_affinity = _chapter_affinity_from_slices(normalized_slices)
    summary.summary_mode = "llm_complete_sections"
    summary.fallback_used = False
    summary.llm_call_count = 1
    return summary


def _failed_routing_summary(packet: SourcePacket, *, attempted: bool) -> FileMaterialSummary:
    """Leave the file unrouted; Writer-time retrieval is the safe fallback."""

    return FileMaterialSummary(
        file_id=packet.file_id,
        filename=packet.filename,
        source_quality=0.0,
        summary_mode="llm_routing_failed" if attempted else "empty_source",
        fallback_used=attempted,
        llm_call_count=1 if attempted else 0,
    )


async def _route_one_batch(
    job: _FileRoutingJob,
    *,
    chapters: Sequence[Mapping[str, Any]],
    digest_mode: str,
    extra_metadata: Mapping[str, Any],
) -> _FileRoutingResult:
    if not any(str(item.normalized_content or "").strip() for item in job.sections):
        return _FileRoutingResult(job.packet.file_id, _failed_routing_summary(job.packet, attempted=False))
    try:
        response = await acompletion_with_fallback(
            build_file_summary_messages(
                filename=(
                    job.packet.filename
                    if job.batch_count == 1
                    else f"{job.packet.filename}（第 {job.batch_index}/{job.batch_count} 批）"
                ),
                digest_mode=digest_mode,
                chapter_contracts=_chapter_contracts(chapters),
                excerpt=_render_complete_sections(job.sections),
                section_catalog=build_section_catalog_for_file(
                    job.packet,
                    sections=job.sections,
                    max_sections=max(1, len(job.sections)),
                ),
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.FILE_SUMMARY,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                docgen_stage="route_complete_file_sections",
                file_id=job.packet.file_id,
                section_batch_index=job.batch_index,
                section_batch_count=job.batch_count,
                section_count=len(job.sections),
            ),
            response_model=FileMaterialSummary,
        )
        summary = response if isinstance(response, FileMaterialSummary) else FileMaterialSummary.model_validate(response)
        return _FileRoutingResult(
            job.packet.file_id,
            _normalize_llm_summary(summary, packet=job.packet, sections=job.sections),
        )
    except Exception as exc:  # pragma: no cover - provider integration
        logger.warning(
            "docgen_file_semantic_routing_failed",
            file_id=job.packet.file_id,
            batch_index=job.batch_index,
            error=str(exc),
        )
        return _FileRoutingResult(job.packet.file_id, _failed_routing_summary(job.packet, attempted=True))


def _merge_file_results(packet: SourcePacket, summaries: Sequence[FileMaterialSummary]) -> FileMaterialSummary:
    if not summaries:
        return _failed_routing_summary(packet, attempted=False)
    slices = _merge_chapter_slices([item for summary in summaries for item in summary.chapter_slices])
    failed = any(item.fallback_used for item in summaries)
    return FileMaterialSummary(
        file_id=packet.file_id,
        filename=packet.filename,
        summary="；".join(clean_string_list([item.summary for item in summaries], limit=12)),
        concepts=clean_string_list([value for item in summaries for value in item.concepts], limit=16),
        definitions=clean_string_list([value for item in summaries for value in item.definitions], limit=16),
        formulas=clean_string_list([value for item in summaries for value in item.formulas], limit=16),
        examples=clean_string_list([value for item in summaries for value in item.examples], limit=16),
        question_types=clean_string_list([value for item in summaries for value in item.question_types], limit=16),
        high_value_sections=_slice_section_refs(slices, limit=64),
        noise_sections=clean_string_list([value for item in summaries for value in item.noise_sections], limit=64),
        chapter_affinity=_chapter_affinity_from_slices(slices),
        chapter_slices=slices,
        source_quality=max((float(item.source_quality or 0.0) for item in summaries), default=0.0),
        summary_mode="llm_partial_sections" if failed else "llm_complete_sections",
        fallback_used=failed,
        llm_call_count=sum(int(item.llm_call_count or 0) for item in summaries),
    )


async def summarize_files(
    material_context: DigestMaterialContext,
    *,
    chapters: Sequence[Mapping[str, Any]],
    digest_mode: str,
    extra_metadata: Mapping[str, Any] | None = None,
) -> list[FileMaterialSummary]:
    """Route every parsed section semantically; independent batches run concurrently."""

    packets = list(material_context.source_packets or [])
    sections = list(material_context.section_packets or [])
    jobs: list[_FileRoutingJob] = []
    for packet in packets:
        batches = _routing_batches(_sections_for_file(sections, packet.file_id)) or [[]]
        jobs.extend(
            _FileRoutingJob(packet, batch, batch_index, len(batches))
            for batch_index, batch in enumerate(batches, start=1)
        )
    results = await run_llm_tasks(
        jobs,
        lambda job: _route_one_batch(
            job,
            chapters=chapters,
            digest_mode=digest_mode,
            extra_metadata=dict(extra_metadata or {}),
        ),
    )
    by_file: dict[str, list[FileMaterialSummary]] = {}
    for result in results:
        by_file.setdefault(result.file_id, []).append(result.summary)
    return [_merge_file_results(packet, by_file.get(packet.file_id, [])) for packet in packets]


def derive_source_affinity_and_evidence(
    material_context: DigestMaterialContext,
    *,
    summaries: Sequence[FileMaterialSummary],
    chapters: Sequence[Mapping[str, Any]],
) -> tuple[list[SourceAffinityByChapter], list[HighConfidenceEvidenceUnit]]:
    """Derive source signals from routed section slices."""

    del material_context
    routed_slices_by_chapter: dict[int, list[ChapterSourceSlice]] = {}
    for summary in summaries:
        for source_slice in list(summary.chapter_slices or []):
            if int(source_slice.chapter_index or 0) <= 0 or not source_slice.section_ref:
                continue
            routed_slices_by_chapter.setdefault(
                int(source_slice.chapter_index),
                [],
            ).append(source_slice)

    affinity_items: list[SourceAffinityByChapter] = []
    evidence_units: list[HighConfidenceEvidenceUnit] = []
    evidence_seen: set[str] = set()
    for index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        routed_slices = sorted(
            routed_slices_by_chapter.get(chapter_index, []),
            key=lambda item: item.relevance,
            reverse=True,
        )
        section_refs = clean_string_list(
            [item.section_ref for item in routed_slices],
        )
        file_ids: list[str] = []
        seen_file_ids: set[str] = set()
        for source_slice in routed_slices:
            if not source_slice.file_id or source_slice.file_id in seen_file_ids:
                continue
            seen_file_ids.add(source_slice.file_id)
            file_ids.append(source_slice.file_id)
        affinity_items.append(
            SourceAffinityByChapter(
                chapter_index=chapter_index,
                file_ids=file_ids,
                section_refs=section_refs,
                source_slices=routed_slices,
                reason=(
                    "Parsed source sections were matched to this confirmed chapter."
                    if routed_slices
                    else "No parsed source section matched this confirmed chapter."
                ),
            )
        )

        for source_slice in routed_slices:
            text = (
                source_slice.summary
                or source_slice.excerpt
                or source_slice.reason
            ).strip()
            if not text:
                continue
            key = f"{source_slice.section_ref}:{text[:80]}".casefold()
            if key in evidence_seen:
                continue
            evidence_seen.add(key)
            evidence_units.append(
                HighConfidenceEvidenceUnit(
                    evidence_id=(
                        f"ch{chapter_index:02d}_{source_slice.section_ref}_"
                        f"{len(evidence_units) + 1:03d}"
                    ),
                    source_ref=(
                        f"local://file/{source_slice.file_id}/section/"
                        f"{source_slice.section_ref}"
                    ),
                    source_type="local",
                    evidence_type=source_slice.usage or "background",
                    text=text,
                    chapter_affinity={
                        chapter_index: max(
                            0.35,
                            min(0.98, source_slice.relevance),
                        )
                    },
                    confidence=max(
                        0.5,
                        min(0.95, source_slice.relevance + 0.08),
                    ),
                    source_title=source_slice.filename or source_slice.section_title,
                    source_span=source_slice.section_ref,
                )
            )

    return affinity_items, evidence_units


__all__ = [
    "derive_source_affinity_and_evidence",
    "summarize_files",
]
