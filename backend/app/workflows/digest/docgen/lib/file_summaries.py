"""Deterministic source routing for DocGen."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib.models import (
    ChapterSourceSlice,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    SourceAffinityByChapter,
    clean_string_list,
)

_FILE_SUMMARY_MAX_MERGED_CHAPTER_SLICES = 48
_ROUTING_STOP_TERMS = {
    "学习",
    "本章",
    "知识",
    "内容",
    "基础",
    "方法",
    "理解",
    "掌握",
    "介绍",
    "分析",
    "计算",
}


def _sections_for_file(sections: Sequence[SectionPacket], file_id: str) -> list[SectionPacket]:
    return [section for section in sections if section.source_file_id == file_id]


def _cap_text(text: object, max_chars: int) -> str:
    cleaned = str(text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(1, max_chars - 3)].rstrip() + "..."


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


def _routing_terms(value: object) -> set[str]:
    """Return compact Chinese n-grams and word tokens for conservative routing."""

    text = str(value or "").casefold()
    terms = {
        match.group(0)
        for match in re.finditer(r"[a-z][a-z0-9_+-]{2,}|\d+(?:\.\d+)?", text)
    }
    for sequence in re.findall(r"[\u3400-\u9fff]+", text):
        if 2 <= len(sequence) <= 8:
            terms.add(sequence)
        for width in (2, 3):
            terms.update(
                sequence[index : index + width]
                for index in range(max(0, len(sequence) - width + 1))
            )
    return {term for term in terms if term not in _ROUTING_STOP_TERMS}


def _chapter_scope(chapter: Mapping[str, Any]) -> str:
    return " ".join(
        [
            str(chapter.get("title") or chapter.get("resolved_title") or ""),
            str(chapter.get("objective") or ""),
            *[str(item) for item in list(chapter.get("required_elements") or [])],
        ]
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


def _deterministic_file_summary(
    packet: SourcePacket,
    *,
    sections: Sequence[SectionPacket],
    chapters: Sequence[Mapping[str, Any]],
) -> FileMaterialSummary:
    """Route parsed sections to confirmed chapters without another model call."""

    usable_sections = [
        section
        for section in sections
        if section.digest_chunk_uid and str(section.normalized_content or "").strip()
    ]
    if not usable_sections:
        return FileMaterialSummary(
            file_id=packet.file_id,
            filename=packet.filename,
            summary=_cap_text(packet.normalized_content, 420),
            source_quality=0.25,
            summary_mode="deterministic_empty_catalog",
            llm_call_count=0,
        )

    candidate_slices: list[ChapterSourceSlice] = []
    for fallback_index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", fallback_index) or fallback_index)
        scope_terms = _routing_terms(_chapter_scope(chapter))
        if not scope_terms:
            continue
        scored: list[tuple[int, int, SectionPacket]] = []
        for section in usable_sections:
            title_text = " ".join([section.title, section.header_path])
            title_overlap = len(scope_terms & _routing_terms(title_text))
            preview_overlap = len(scope_terms & _routing_terms(section.preview))
            score = title_overlap * 4 + preview_overlap
            if score > 0:
                scored.append((score, -int(section.chunk_index or 0), section))
        for score, _order, section in sorted(
            scored,
            reverse=True,
            key=lambda item: (item[0], item[1]),
        )[:6]:
            title = section.title or section.header_path or f"Section {section.chunk_index + 1}"
            preview = _cap_text(section.preview or section.normalized_content, 220)
            candidate_slices.append(
                ChapterSourceSlice(
                    chapter_index=chapter_index,
                    file_id=packet.file_id,
                    filename=packet.filename,
                    section_ref=section.digest_chunk_uid,
                    section_title=title,
                    header_path=section.header_path,
                    relevance=min(0.92, 0.52 + score * 0.025),
                    usage="context",
                    reason="依据确认章节与解析切片标题/预览的确定性匹配。",
                    summary=preview,
                    excerpt=preview,
                )
            )

    chapter_slices = _merge_chapter_slices(candidate_slices)
    selected_refs = _slice_section_refs(chapter_slices)
    selected_ref_set = set(selected_refs)
    selected_sections = [
        section
        for section in usable_sections
        if section.digest_chunk_uid in selected_ref_set
    ]
    summary_titles = clean_string_list(
        [
            section.title or section.header_path
            for section in (selected_sections or usable_sections[:6])
        ],
        limit=8,
    )
    return FileMaterialSummary(
        file_id=packet.file_id,
        filename=packet.filename,
        summary=_cap_text("；".join(summary_titles) or packet.normalized_content, 700),
        concepts=summary_titles,
        high_value_sections=selected_refs,
        chapter_affinity=_chapter_affinity_from_slices(chapter_slices),
        chapter_slices=chapter_slices,
        source_quality=0.6 if chapter_slices else 0.4,
        summary_mode="deterministic_section_routing",
        fallback_used=False,
        llm_call_count=0,
    )


def summarize_files_deterministically(
    material_context: DigestMaterialContext,
    *,
    chapters: Sequence[Mapping[str, Any]],
) -> list[FileMaterialSummary]:
    """Build source routing summaries from parsed material and the confirmed plan."""

    sections = list(material_context.section_packets or [])
    return [
        _deterministic_file_summary(
            packet,
            sections=_sections_for_file(sections, packet.file_id),
            chapters=chapters,
        )
        for packet in list(material_context.source_packets or [])
    ]


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
        )[:14]
        section_refs = clean_string_list(
            [item.section_ref for item in routed_slices],
            limit=14,
        )
        file_ids: list[str] = []
        seen_file_ids: set[str] = set()
        for source_slice in routed_slices:
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
                source_slices=routed_slices,
                reason=(
                    "Parsed source sections were matched to this confirmed chapter."
                    if routed_slices
                    else "No parsed source section matched this confirmed chapter."
                ),
            )
        )

        for source_slice in routed_slices[:10]:
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
                    text=text[:240],
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

    if not evidence_units:
        for summary in summaries[:12]:
            text_candidates = clean_string_list(
                [*summary.definitions, *summary.concepts, summary.summary],
                limit=4,
            )
            for candidate in text_candidates[:2]:
                chapter_affinity = {
                    chapter_index: score
                    for chapter_index, score in summary.chapter_affinity.items()
                    if score > 0
                }
                evidence_units.append(
                    HighConfidenceEvidenceUnit(
                        evidence_id=(
                            f"file{summary.file_id}_ev"
                            f"{len(evidence_units) + 1:03d}"
                        ),
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


__all__ = [
    "derive_source_affinity_and_evidence",
    "summarize_files_deterministically",
]
