"""DocGen-oriented source file summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
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

_FILE_SUMMARY_MAX_EXCERPT_CHARS = 36_000
_FILE_SUMMARY_HEAD_CHARS = 12_000
_FILE_SUMMARY_TAIL_CHARS = 8_000
_FILE_SUMMARY_SECTION_SAMPLE_CHARS = 900
_FILE_SUMMARY_SECTION_SAMPLE_COUNT = 16
_FILE_SUMMARY_LONG_BATCH_TARGET_CHARS = 24_000
_FILE_SUMMARY_LONG_BATCH_EXCERPT_CHARS = 18_000
_FILE_SUMMARY_MAX_SECTIONS_PER_BATCH = 80
_FILE_SUMMARY_MAX_MERGED_CHAPTER_SLICES = 48


class FileSummaryRoutingError(RuntimeError):
    """Raised when the LLM cannot produce a usable source-routing summary."""


@dataclass(frozen=True)
class _FileSectionBatch:
    """One ordered section batch used to parallelize long-file summaries."""

    batch_index: int
    total_batches: int
    sections: list[SectionPacket]


@dataclass(frozen=True)
class _FileSummaryJob:
    """One LLM summary job under the shared DocGen file-summary concurrency gate."""

    packet: SourcePacket
    sections: list[SectionPacket]
    batch: _FileSectionBatch | None = None


@dataclass(frozen=True)
class _FileSummaryJobResult:
    """One completed file-summary job, ready to regroup by source file."""

    file_id: str
    summary: FileMaterialSummary
    batch_mode: bool


def _sections_for_file(sections: Sequence[SectionPacket], file_id: str) -> list[SectionPacket]:
    return [section for section in sections if section.source_file_id == file_id]


def _cap_text(text: str, max_chars: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(1, max_chars - 3)].rstrip() + "..."


def _build_file_summary_excerpt(packet: SourcePacket, sections: Sequence[SectionPacket]) -> str:
    """Return a bounded source sample for the LLM file-summary router."""

    content = str(packet.normalized_content or "").strip()
    if len(content) <= _FILE_SUMMARY_MAX_EXCERPT_CHARS:
        return content

    blocks: list[str] = []
    head = _cap_text(content[:_FILE_SUMMARY_HEAD_CHARS], _FILE_SUMMARY_HEAD_CHARS)
    if head:
        blocks.append(f"## Source head\n{head}")

    priority_sections = sorted(
        list(sections),
        key=lambda item: (item.question_block_count, len(item.formula_refs), item.char_count),
        reverse=True,
    )[:_FILE_SUMMARY_SECTION_SAMPLE_COUNT]
    for section in priority_sections:
        excerpt = _cap_text(section.normalized_content, _FILE_SUMMARY_SECTION_SAMPLE_CHARS)
        if not excerpt:
            continue
        title = section.title or section.header_path or f"Part {section.chunk_index + 1}"
        blocks.append(
            "\n".join(
                [
                    f"## Priority section {section.digest_chunk_uid}",
                    f"Title: {title}",
                    f"Preview: {section.preview}",
                    excerpt,
                ]
            ).strip()
        )

    tail = _cap_text(content[-_FILE_SUMMARY_TAIL_CHARS:], _FILE_SUMMARY_TAIL_CHARS)
    if tail:
        blocks.append(f"## Source tail\n{tail}")

    sampled = "\n\n".join(blocks).strip()
    if len(sampled) <= _FILE_SUMMARY_MAX_EXCERPT_CHARS:
        return sampled
    omitted = "\n\n...[middle content omitted from this bounded file-level sample; section routing must use the catalog]..."
    return sampled[: max(1, _FILE_SUMMARY_MAX_EXCERPT_CHARS - len(omitted))].rstrip() + omitted


def _build_section_batch_excerpt(
    batch: _FileSectionBatch,
    *,
    max_chars: int = _FILE_SUMMARY_LONG_BATCH_EXCERPT_CHARS,
) -> str:
    """Render exact section-batch excerpts for long-file routing."""

    sections = list(batch.sections)
    if not sections:
        return ""
    per_section_chars = max(260, min(1400, int(max_chars / max(1, len(sections)))))
    blocks: list[str] = []
    used_chars = 0
    for section in sections:
        excerpt = _cap_text(section.normalized_content, per_section_chars)
        if not excerpt:
            continue
        block = "\n".join(
            [
                f"## Section {section.digest_chunk_uid}",
                f"Title: {section.title or section.header_path}",
                f"Header path: {section.header_path}",
                f"Page: {section.page_num or 'unknown'}",
                f"Preview: {section.preview}",
                "",
                excerpt,
            ]
        ).strip()
        if used_chars + len(block) > max_chars and blocks:
            blocks.append("...[more sections in this batch omitted; choose section_ref only from the catalog]...")
            break
        blocks.append(block)
        used_chars += len(block)
    return "\n\n".join(blocks).strip()


def _build_long_file_section_batches(
    packet: SourcePacket,
    sections: Sequence[SectionPacket],
) -> list[_FileSectionBatch]:
    """Split a long file into bounded ordered batches for parallel LLM routing."""

    file_sections = _sections_for_file(sections, packet.file_id)
    if not file_sections:
        return []
    content_chars = len(str(packet.normalized_content or ""))
    if content_chars <= _FILE_SUMMARY_MAX_EXCERPT_CHARS and len(file_sections) <= _FILE_SUMMARY_MAX_SECTIONS_PER_BATCH:
        return []

    total_section_chars = sum(max(1, section.char_count) for section in file_sections)
    desired_batches = max(
        2,
        ceil(max(content_chars, total_section_chars) / _FILE_SUMMARY_LONG_BATCH_TARGET_CHARS),
        ceil(len(file_sections) / _FILE_SUMMARY_MAX_SECTIONS_PER_BATCH),
    )
    desired_batches = min(desired_batches, len(file_sections))
    target_chars = max(1, ceil(total_section_chars / desired_batches))
    target_sections = max(1, ceil(len(file_sections) / desired_batches))

    raw_batches: list[list[SectionPacket]] = []
    current: list[SectionPacket] = []
    current_chars = 0
    for section in file_sections:
        should_flush = bool(
            current
            and len(raw_batches) < desired_batches - 1
            and (
                current_chars + max(1, section.char_count) > target_chars
                or len(current) >= target_sections
            )
        )
        if should_flush:
            raw_batches.append(current)
            current = []
            current_chars = 0
        current.append(section)
        current_chars += max(1, section.char_count)
    if current:
        raw_batches.append(current)

    if len(raw_batches) <= 1:
        return []
    total_batches = len(raw_batches)
    return [
        _FileSectionBatch(batch_index=index + 1, total_batches=total_batches, sections=batch)
        for index, batch in enumerate(raw_batches)
        if batch
    ]


def _normalize_summary_slices(
    summary: FileMaterialSummary,
    *,
    packet: SourcePacket,
    sections: Sequence[SectionPacket],
) -> FileMaterialSummary:
    catalog_by_ref = {
        item["section_ref"]: item
        for item in build_section_catalog_for_file(
            packet,
            sections=list(sections),
            max_sections=max(1, len(sections)),
        )
        if str(item.get("section_ref") or "").strip()
    }
    normalized: list[ChapterSourceSlice] = []
    seen: set[str] = set()
    for raw_slice in list(summary.chapter_slices or []):
        source_slice = raw_slice if isinstance(raw_slice, ChapterSourceSlice) else ChapterSourceSlice.model_validate(raw_slice)
        catalog_item = catalog_by_ref.get(source_slice.section_ref)
        if catalog_item is None or int(source_slice.chapter_index or 0) <= 0:
            continue
        key = f"{source_slice.chapter_index}:{source_slice.section_ref}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            ChapterSourceSlice(
                chapter_index=source_slice.chapter_index,
                file_id=packet.file_id,
                filename=packet.filename,
                section_ref=source_slice.section_ref,
                section_title=source_slice.section_title or str(catalog_item.get("title") or ""),
                header_path=source_slice.header_path or str(catalog_item.get("header_path") or ""),
                line_start=source_slice.line_start or catalog_item.get("line_start"),
                line_end=source_slice.line_end or catalog_item.get("line_end"),
                relevance=source_slice.relevance,
                usage=source_slice.usage,
                reason=source_slice.reason,
                summary=source_slice.summary,
                excerpt=source_slice.excerpt,
            )
        )
        if len(normalized) >= 24:
            break
    summary.chapter_slices = normalized
    return summary


def _chapter_affinity_from_slices(slices: Sequence[ChapterSourceSlice]) -> dict[int, float]:
    affinity: dict[int, float] = {}
    for source_slice in slices:
        try:
            chapter_index = int(source_slice.chapter_index)
        except (TypeError, ValueError):
            continue
        if chapter_index <= 0:
            continue
        affinity[chapter_index] = max(float(affinity.get(chapter_index, 0.0)), float(source_slice.relevance or 0.0))
    return affinity


def _slice_section_refs(slices: Sequence[ChapterSourceSlice], *, limit: int = 24) -> list[str]:
    return clean_string_list([source_slice.section_ref for source_slice in slices if source_slice.section_ref], limit=limit)


def _has_explicit_noise(summary: FileMaterialSummary, sections: Sequence[SectionPacket]) -> bool:
    section_refs = {section.digest_chunk_uid for section in sections if section.digest_chunk_uid}
    noise_refs = {ref for ref in clean_string_list(summary.noise_sections, limit=max(16, len(section_refs)))}
    return bool(section_refs & noise_refs)


def _chapter_indices_from_titles(chapter_titles: Sequence[str]) -> list[int]:
    return [index + 1 for index, title in enumerate(chapter_titles) if str(title or "").strip()] or [1]


def _chapter_indices_from_chapters(chapters: Sequence[Mapping[str, Any]]) -> list[int]:
    indices: list[int] = []
    for offset, chapter in enumerate(chapters):
        try:
            chapter_index = int(chapter.get("chapter_index") or chapter.get("index") or offset + 1)
        except (TypeError, ValueError):
            chapter_index = offset + 1
        if chapter_index > 0:
            indices.append(chapter_index)
    return indices or [1]


def _fallback_file_summary(
    packet: SourcePacket,
    *,
    sections: Sequence[SectionPacket],
    chapter_indices: Sequence[int],
    summary_mode: str,
) -> FileMaterialSummary:
    """Build a conservative local routing summary when the summary LLM is unavailable."""

    usable_sections = [
        section
        for section in sections
        if section.digest_chunk_uid and str(section.normalized_content or "").strip()
    ]
    if not usable_sections:
        return FileMaterialSummary(
            file_id=packet.file_id,
            filename=packet.filename,
            summary=_cap_text(str(packet.normalized_content or "").strip(), 360),
            source_quality=0.25,
            summary_mode=summary_mode,
            fallback_used=True,
        )

    ordered_sections = sorted(
        usable_sections,
        key=lambda item: (item.question_block_count, len(item.formula_refs), item.char_count),
        reverse=True,
    )
    selected_sections = ordered_sections[: min(24, max(1, len(ordered_sections)))]
    resolved_indices = [index for index in chapter_indices if int(index or 0) > 0] or [1]
    chapter_slices: list[ChapterSourceSlice] = []
    high_value_sections: list[str] = []
    concepts: list[str] = []
    for position, section in enumerate(selected_sections):
        chapter_index = resolved_indices[position % len(resolved_indices)]
        title = section.title or section.header_path or f"Section {section.chunk_index + 1}"
        preview = _cap_text(section.preview or section.normalized_content, 180)
        high_value_sections.append(section.digest_chunk_uid)
        concepts.append(title)
        chapter_slices.append(
            ChapterSourceSlice(
                chapter_index=chapter_index,
                file_id=packet.file_id,
                filename=packet.filename,
                section_ref=section.digest_chunk_uid,
                section_title=title,
                header_path=section.header_path,
                line_start=getattr(section, "line_start", None),
                line_end=getattr(section, "line_end", None),
                relevance=0.55,
                usage="context",
                reason="LLM 文件摘要不可用时的本地保守路由。",
                summary=preview,
                excerpt=preview,
            )
        )

    summary_parts = [
        section.title or section.header_path or section.preview
        for section in selected_sections[:6]
        if str(section.title or section.header_path or section.preview or "").strip()
    ]
    summary = "；".join(summary_parts) or _cap_text(str(packet.normalized_content or "").strip(), 420)
    return FileMaterialSummary(
        file_id=packet.file_id,
        filename=packet.filename,
        summary=_cap_text(summary, 700),
        concepts=clean_string_list(concepts, limit=16),
        high_value_sections=clean_string_list(high_value_sections, limit=24),
        chapter_affinity=_chapter_affinity_from_slices(chapter_slices),
        chapter_slices=chapter_slices,
        source_quality=0.45,
        summary_mode=summary_mode,
        fallback_used=True,
        llm_call_count=0,
    )


def _merge_affinity(*items: Mapping[int, float]) -> dict[int, float]:
    merged: dict[int, float] = {}
    for item in items:
        for raw_index, raw_score in dict(item or {}).items():
            try:
                index = int(raw_index)
                score = float(raw_score or 0.0)
            except (TypeError, ValueError):
                continue
            if index <= 0:
                continue
            merged[index] = max(float(merged.get(index, 0.0)), max(0.0, min(1.0, score)))
    return merged


def _finalize_llm_summary(
    summary: FileMaterialSummary,
    *,
    packet: SourcePacket,
    sections: Sequence[SectionPacket],
    stage: str,
    llm_call_count: int,
    summary_mode: str,
) -> FileMaterialSummary:
    summary.file_id = packet.file_id
    summary.filename = packet.filename
    summary = _normalize_summary_slices(summary, packet=packet, sections=sections)
    if sections and not summary.chapter_slices and not _has_explicit_noise(summary, sections):
        raise FileSummaryRoutingError(
            f"LLM file summary for {packet.file_id} produced no chapter_slices or explicit noise_sections during {stage}."
        )

    slice_affinity = _chapter_affinity_from_slices(summary.chapter_slices)
    summary.chapter_affinity = _merge_affinity(summary.chapter_affinity, slice_affinity)
    if not summary.high_value_sections:
        summary.high_value_sections = _slice_section_refs(summary.chapter_slices)
    summary.summary_mode = summary.summary_mode if summary.summary_mode and summary.summary_mode != "fallback" else summary_mode
    summary.fallback_used = False
    summary.llm_call_count = llm_call_count
    return summary


def _merge_chapter_affinity(summaries: Sequence[FileMaterialSummary]) -> dict[int, float]:
    merged: dict[int, float] = {}
    for summary in summaries:
        merged = _merge_affinity(merged, summary.chapter_affinity)
    return merged


def _merge_chapter_slices(summaries: Sequence[FileMaterialSummary]) -> list[ChapterSourceSlice]:
    deduped: dict[str, ChapterSourceSlice] = {}
    for summary in summaries:
        for source_slice in list(summary.chapter_slices or []):
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
        chapter_slices.sort(key=lambda item: (-float(item.relevance or 0.0), item.section_ref))

    chapter_indices = sorted(
        slices_by_chapter,
        key=lambda index: (-float(slices_by_chapter[index][0].relevance or 0.0), index),
    )
    balanced: list[ChapterSourceSlice] = []
    cursor = 0
    while len(balanced) < _FILE_SUMMARY_MAX_MERGED_CHAPTER_SLICES:
        added = False
        for chapter_index in chapter_indices:
            chapter_slices = slices_by_chapter[chapter_index]
            if cursor >= len(chapter_slices):
                continue
            balanced.append(chapter_slices[cursor])
            added = True
            if len(balanced) >= _FILE_SUMMARY_MAX_MERGED_CHAPTER_SLICES:
                break
        if not added:
            break
        cursor += 1
    return balanced


def _merge_file_summary_batches(
    packet: SourcePacket,
    *,
    summaries: Sequence[FileMaterialSummary],
) -> FileMaterialSummary:
    usable = [summary for summary in summaries if summary is not None]
    if not usable:
        raise FileSummaryRoutingError(f"LLM produced no section-batch summaries for {packet.file_id}.")
    summary_text = " ".join(clean_string_list([item.summary for item in usable], limit=8))
    if len(summary_text) > 700:
        summary_text = summary_text[:697].rstrip() + "..."
    chapter_slices = _merge_chapter_slices(usable)
    if not chapter_slices and not any(item.noise_sections for item in usable):
        raise FileSummaryRoutingError(f"LLM produced no routed slices or explicit noise sections for {packet.file_id}.")
    merged = FileMaterialSummary(
        file_id=packet.file_id,
        filename=packet.filename,
        summary=summary_text,
        concepts=clean_string_list([value for item in usable for value in item.concepts], limit=16),
        definitions=clean_string_list([value for item in usable for value in item.definitions], limit=16),
        formulas=clean_string_list([value for item in usable for value in item.formulas], limit=16),
        examples=clean_string_list([value for item in usable for value in item.examples], limit=16),
        question_types=clean_string_list([value for item in usable for value in item.question_types], limit=16),
        high_value_sections=clean_string_list(
            [
                *[value for item in usable for value in item.high_value_sections],
                *_slice_section_refs(chapter_slices),
            ],
            limit=24,
        ),
        noise_sections=clean_string_list([value for item in usable for value in item.noise_sections], limit=24),
        chapter_affinity=_merge_chapter_affinity(usable) or _chapter_affinity_from_slices(chapter_slices),
        chapter_slices=chapter_slices,
        source_quality=max([float(item.source_quality or 0.0) for item in usable] + [0.0]),
        summary_mode="fallback_section_batches" if any(item.fallback_used for item in usable) else "llm_section_batches",
        fallback_used=any(item.fallback_used for item in usable),
        llm_call_count=sum(max(0, int(item.llm_call_count or 0)) for item in usable),
    )
    return merged


def derive_source_affinity_and_evidence(
    material_context: DigestMaterialContext,
    *,
    summaries: Sequence[FileMaterialSummary],
    chapters: Sequence[Mapping[str, Any]],
) -> tuple[list[SourceAffinityByChapter], list[HighConfidenceEvidenceUnit]]:
    """Derive source signals from LLM-routed section slices."""

    del material_context
    llm_slices_by_chapter: dict[int, list[ChapterSourceSlice]] = {}
    for summary in summaries:
        for source_slice in list(summary.chapter_slices or []):
            if int(source_slice.chapter_index or 0) <= 0 or not source_slice.section_ref:
                continue
            llm_slices_by_chapter.setdefault(int(source_slice.chapter_index), []).append(source_slice)
    affinity_items: list[SourceAffinityByChapter] = []
    evidence_units: list[HighConfidenceEvidenceUnit] = []
    evidence_seen: set[str] = set()

    for index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        llm_slices = sorted(
            llm_slices_by_chapter.get(chapter_index, []),
            key=lambda item: item.relevance,
            reverse=True,
        )[:14]
        section_refs = clean_string_list([item.section_ref for item in llm_slices], limit=14)
        file_ids = []
        seen_file_ids: set[str] = set()
        for source_slice in llm_slices:
            if not source_slice.file_id or source_slice.file_id in seen_file_ids:
                continue
            seen_file_ids.add(source_slice.file_id)
            file_ids.append(source_slice.file_id)
            if len(file_ids) >= 8:
                break
        affinity_items.append(
            SourceAffinityByChapter(
                chapter_index=chapter_index,
                file_ids=file_ids,
                section_refs=section_refs,
                source_slices=llm_slices,
                reason=(
                    "LLM routed local source slices for this chapter."
                    if llm_slices
                    else "LLM did not route local source slices for this chapter."
                ),
            )
        )

        for source_slice in llm_slices[:10]:
            text = (source_slice.summary or source_slice.excerpt or source_slice.reason).strip()
            if not text:
                continue
            key = f"{source_slice.section_ref}:{text[:80]}".casefold()
            if key in evidence_seen:
                continue
            evidence_seen.add(key)
            evidence_units.append(
                HighConfidenceEvidenceUnit(
                    evidence_id=f"ch{chapter_index:02d}_{source_slice.section_ref}_{len(evidence_units) + 1:03d}",
                    source_ref=f"local://file/{source_slice.file_id}/section/{source_slice.section_ref}",
                    source_type="local",
                    evidence_type=source_slice.usage or "background",
                    text=text[:240],
                    chapter_affinity={chapter_index: max(0.35, min(0.98, source_slice.relevance))},
                    confidence=max(0.5, min(0.95, source_slice.relevance + 0.08)),
                    source_title=source_slice.filename or source_slice.section_title,
                    source_span=source_slice.section_ref,
                )
            )

    if not evidence_units:
        for summary in summaries[:12]:
            text_candidates = clean_string_list([*summary.definitions, *summary.concepts, summary.summary], limit=4)
            for candidate in text_candidates[:2]:
                chapter_affinity = {
                    chapter_index: score
                    for chapter_index, score in summary.chapter_affinity.items()
                    if score > 0
                }
                evidence_units.append(
                    HighConfidenceEvidenceUnit(
                        evidence_id=f"file{summary.file_id}_ev{len(evidence_units) + 1:03d}",
                        source_ref=f"local://file/{summary.file_id}",
                        source_type="local",
                        evidence_type="background",
                        text=candidate[:240],
                        chapter_affinity=chapter_affinity,
                        confidence=0.65,
                        source_title=summary.filename,
                    )
                )
    return affinity_items, evidence_units[:80]


async def _summarize_one_file(
    packet: SourcePacket,
    *,
    sections: Sequence[SectionPacket],
    chapters: Sequence[Mapping[str, Any]],
    digest_mode: str,
    extra_metadata: Mapping[str, Any],
) -> FileMaterialSummary:
    chapter_titles = [
        str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
        for chapter in chapters
        if str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
    ]
    file_sections = _sections_for_file(sections, packet.file_id)
    if not str(packet.normalized_content or "").strip():
        return FileMaterialSummary(
            file_id=packet.file_id,
            filename=packet.filename,
            source_quality=0.0,
            summary_mode="empty_source",
            fallback_used=False,
        )
    if not file_sections:
        raise FileSummaryRoutingError(f"No section packets are available for non-empty source file {packet.file_id}.")

    section_catalog = build_section_catalog_for_file(packet, sections=file_sections, max_sections=max(1, len(file_sections)))
    excerpt = _build_file_summary_excerpt(packet, file_sections)
    try:
        response = await acompletion_with_fallback(
            build_file_summary_messages(
                filename=packet.filename,
                digest_mode=digest_mode,
                chapter_titles=chapter_titles,
                excerpt=excerpt,
                section_catalog=section_catalog,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.FILE_SUMMARY,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                docgen_stage="summarize_file",
                file_id=packet.file_id,
            ),
            response_model=FileMaterialSummary,
        )
    except Exception as exc:
        logger.warning("docgen_file_summary_failed", file_id=packet.file_id, error=str(exc))
        return _fallback_file_summary(
            packet,
            sections=file_sections,
            chapter_indices=_chapter_indices_from_chapters(chapters),
            summary_mode="fallback_file_summary",
        )
    try:
        summary = response if isinstance(response, FileMaterialSummary) else FileMaterialSummary.model_validate(response)
    except Exception as exc:
        logger.warning("docgen_file_summary_invalid_schema", file_id=packet.file_id, error=str(exc))
        return _fallback_file_summary(
            packet,
            sections=file_sections,
            chapter_indices=_chapter_indices_from_chapters(chapters),
            summary_mode="fallback_file_summary",
        )
    return _finalize_llm_summary(
        summary,
        packet=packet,
        sections=file_sections,
        stage="file",
        llm_call_count=1,
        summary_mode="llm_sampled",
    )


async def _summarize_one_file_batch(
    packet: SourcePacket,
    *,
    batch: _FileSectionBatch,
    chapter_titles: Sequence[str],
    digest_mode: str,
    extra_metadata: Mapping[str, Any],
) -> FileMaterialSummary:
    section_catalog = build_section_catalog_for_file(
        packet,
        sections=list(batch.sections),
        max_sections=max(1, len(batch.sections)),
    )
    excerpt = _build_section_batch_excerpt(batch)
    try:
        response = await acompletion_with_fallback(
            build_file_summary_messages(
                filename=f"{packet.filename} section batch {batch.batch_index}/{batch.total_batches}",
                digest_mode=digest_mode,
                chapter_titles=list(chapter_titles),
                excerpt=excerpt,
                section_catalog=section_catalog,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.FILE_SUMMARY,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                docgen_stage="summarize_file_section_batch",
                file_id=packet.file_id,
                section_batch_index=batch.batch_index,
                section_batch_total=batch.total_batches,
                section_count=len(batch.sections),
            ),
            response_model=FileMaterialSummary,
        )
    except Exception as exc:
        logger.warning(
            "docgen_file_section_batch_summary_failed",
            file_id=packet.file_id,
            section_batch_index=batch.batch_index,
            error=str(exc),
        )
        return _fallback_file_summary(
            packet,
            sections=batch.sections,
            chapter_indices=_chapter_indices_from_titles(chapter_titles),
            summary_mode="fallback_section_batch",
        )
    try:
        summary = response if isinstance(response, FileMaterialSummary) else FileMaterialSummary.model_validate(response)
    except Exception as exc:
        logger.warning(
            "docgen_file_section_batch_summary_invalid_schema",
            file_id=packet.file_id,
            section_batch_index=batch.batch_index,
            error=str(exc),
        )
        return _fallback_file_summary(
            packet,
            sections=batch.sections,
            chapter_indices=_chapter_indices_from_titles(chapter_titles),
            summary_mode="fallback_section_batch",
        )
    return _finalize_llm_summary(
        summary,
        packet=packet,
        sections=batch.sections,
        stage=f"section batch {batch.batch_index}/{batch.total_batches}",
        llm_call_count=1,
        summary_mode="llm_section_batch",
    )


async def _run_file_summary_job(
    job: _FileSummaryJob,
    *,
    chapter_titles: Sequence[str],
    chapters: Sequence[Mapping[str, Any]],
    digest_mode: str,
    extra_metadata: Mapping[str, Any],
) -> _FileSummaryJobResult:
    if job.batch is not None:
        summary = await _summarize_one_file_batch(
            job.packet,
            batch=job.batch,
            chapter_titles=chapter_titles,
            digest_mode=digest_mode,
            extra_metadata=extra_metadata,
        )
        return _FileSummaryJobResult(
            file_id=job.packet.file_id,
            summary=summary,
            batch_mode=True,
        )
    summary = await _summarize_one_file(
        job.packet,
        sections=job.sections,
        chapters=chapters,
        digest_mode=digest_mode,
        extra_metadata=extra_metadata,
    )
    return _FileSummaryJobResult(
        file_id=job.packet.file_id,
        summary=summary,
        batch_mode=False,
    )


async def summarize_files(
    material_context: DigestMaterialContext,
    *,
    chapters: Sequence[Mapping[str, Any]],
    digest_mode: str,
    extra_metadata: Mapping[str, Any] | None = None,
) -> list[FileMaterialSummary]:
    packets = list(material_context.source_packets or [])
    if not packets:
        return []
    sections = list(material_context.section_packets or [])
    chapter_titles = [
        str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
        for chapter in chapters
        if str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
    ]
    file_sections_by_id: dict[str, list[SectionPacket]] = {}
    batched_file_ids: set[str] = set()
    batch_count_by_file: dict[str, int] = {}
    jobs: list[_FileSummaryJob] = []
    for packet in packets:
        file_sections = _sections_for_file(sections, packet.file_id)
        file_sections_by_id[packet.file_id] = file_sections
        section_batches = _build_long_file_section_batches(packet, file_sections)
        if section_batches:
            batched_file_ids.add(packet.file_id)
            batch_count_by_file[packet.file_id] = len(section_batches)
            jobs.extend(
                _FileSummaryJob(packet=packet, sections=file_sections, batch=batch)
                for batch in section_batches
            )
        else:
            jobs.append(_FileSummaryJob(packet=packet, sections=file_sections))

    metadata = dict(extra_metadata or {})
    results = await run_llm_tasks(
        jobs,
        lambda job: _run_file_summary_job(
            job,
            chapter_titles=chapter_titles,
            chapters=chapters,
            digest_mode=digest_mode,
            extra_metadata=metadata,
        ),
    )
    batch_summaries_by_file: dict[str, list[FileMaterialSummary]] = {}
    single_summaries_by_file: dict[str, FileMaterialSummary] = {}
    for result in results:
        if result.batch_mode:
            batch_summaries_by_file.setdefault(result.file_id, []).append(result.summary)
        else:
            single_summaries_by_file[result.file_id] = result.summary

    summaries: list[FileMaterialSummary] = []
    for packet in packets:
        file_sections = file_sections_by_id.get(packet.file_id, [])
        if packet.file_id in batched_file_ids:
            file_batch_summaries = batch_summaries_by_file.get(packet.file_id, [])
            expected_batch_count = batch_count_by_file.get(packet.file_id, 0)
            if len(file_batch_summaries) != expected_batch_count:
                raise FileSummaryRoutingError(
                    f"LLM returned {len(file_batch_summaries)} of {expected_batch_count} section-batch summaries for {packet.file_id}."
                )
            merged = _merge_file_summary_batches(
                packet,
                summaries=file_batch_summaries,
            )
            summaries.append(_normalize_summary_slices(merged, packet=packet, sections=file_sections))
        else:
            summary = single_summaries_by_file.get(packet.file_id)
            if summary is None:
                raise FileSummaryRoutingError(f"LLM returned no file summary for {packet.file_id}.")
            summaries.append(summary)
    return summaries


__all__ = [
    "FileSummaryRoutingError",
    "derive_source_affinity_and_evidence",
    "summarize_files",
]
