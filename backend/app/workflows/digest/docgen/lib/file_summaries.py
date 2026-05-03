"""DocGen-oriented source file summaries."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback, get_llm_concurrency_limit
from app.shared.infra.runtime import gather_with_concurrency
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
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

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_FORMULA_RE = re.compile(r"\$\$?([^$\n]{2,120})\$\$?", re.DOTALL)
_QUESTION_RE = re.compile(r"(例题|习题|选择题|填空题|简答题|证明题|计算题|真题|练习)")
_EVIDENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s+|\n+")


def _sections_for_file(sections: Sequence[SectionPacket], file_id: str) -> list[SectionPacket]:
    return [section for section in sections if section.source_file_id == file_id]


def fallback_file_summary(
    packet: SourcePacket,
    *,
    sections: Sequence[SectionPacket],
    chapters: Sequence[Mapping[str, Any]],
) -> FileMaterialSummary:
    file_sections = _sections_for_file(sections, packet.file_id)
    headings = clean_string_list(
        [
            *[section.title for section in file_sections if section.title],
            *_HEADING_RE.findall(packet.normalized_content or ""),
        ],
        limit=16,
    )
    formulas = clean_string_list(_FORMULA_RE.findall(packet.normalized_content or ""), limit=8)
    question_types = ["题目/练习"] if _QUESTION_RE.search(packet.normalized_content or "") else []
    affinity: dict[int, float] = {}
    haystack = f"{packet.filename}\n{packet.normalized_content[:8000]}".casefold()
    for index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        terms = clean_string_list(
            [
                chapter.get("title"),
                chapter.get("resolved_title"),
                chapter.get("objective"),
                *list(chapter.get("required_elements", []) or []),
            ],
            limit=10,
        )
        hits = sum(1 for term in terms if term.casefold() in haystack)
        affinity[chapter_index] = min(1.0, hits / max(2, len(terms) or 1))
    return FileMaterialSummary(
        file_id=packet.file_id,
        filename=packet.filename,
        summary=f"{packet.filename} 包含 {len(file_sections)} 个切片，约 {packet.char_count} 字。",
        concepts=headings[:10],
        definitions=headings[:6],
        formulas=formulas,
        examples=[section.title for section in file_sections if section.question_block_count > 0][:8],
        question_types=question_types,
        high_value_sections=[
            section.digest_chunk_uid
            for section in sorted(
                file_sections,
                key=lambda item: (item.question_block_count, len(item.formula_refs), item.char_count),
                reverse=True,
            )[:8]
        ],
        noise_sections=[],
        chapter_affinity=affinity,
        source_quality=0.72 if packet.char_count > 1000 else 0.45,
        summary_mode="rule_sampled",
        fallback_used=True,
    )


def _normalize_summary_slices(
    summary: FileMaterialSummary,
    *,
    packet: SourcePacket,
    sections: Sequence[SectionPacket],
) -> FileMaterialSummary:
    catalog_by_ref = {
        item["section_ref"]: item
        for item in build_section_catalog_for_file(packet, sections=list(sections))
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


def _chapter_terms(chapter: Mapping[str, Any]) -> list[str]:
    return clean_string_list(
        [
            chapter.get("title"),
            chapter.get("resolved_title"),
            chapter.get("objective"),
            *list(chapter.get("required_elements", []) or []),
        ],
        limit=12,
    )


def _evidence_type(text: str) -> str:
    if any(marker in text for marker in ("公式", "定理", "性质", "$", "=")):
        return "formula"
    if any(marker in text for marker in ("例题", "习题", "练习", "题型", "应用")):
        return "example"
    if any(marker in text for marker in ("易错", "误区", "注意", "不能", "陷阱")):
        return "pitfall"
    if any(marker in text for marker in ("定义", "概念", "称为", "是指")):
        return "definition"
    return "background"


def _section_score_for_chapter(section: SectionPacket, terms: Sequence[str]) -> float:
    haystack = f"{section.title}\n{section.header_path}\n{section.preview}\n{section.normalized_content[:1200]}".casefold()
    hits = sum(1 for term in terms if term.casefold() in haystack)
    density_bonus = 0.0
    if section.question_block_count > 0:
        density_bonus += 0.12
    if section.formula_refs:
        density_bonus += 0.12
    if section.char_count >= 500:
        density_bonus += 0.08
    return min(1.0, (hits / max(2, len(terms) or 1)) + density_bonus)


def derive_source_affinity_and_evidence(
    material_context: DigestMaterialContext,
    *,
    summaries: Sequence[FileMaterialSummary],
    chapters: Sequence[Mapping[str, Any]],
) -> tuple[list[SourceAffinityByChapter], list[HighConfidenceEvidenceUnit]]:
    """Derive source signals, preferring LLM-routed section slices."""

    sections = list(material_context.section_packets or [])
    summaries_by_file = {summary.file_id: summary for summary in summaries if summary.file_id}
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
        terms = _chapter_terms(chapter)
        llm_slices = sorted(
            llm_slices_by_chapter.get(chapter_index, []),
            key=lambda item: item.relevance,
            reverse=True,
        )[:14]
        scored_sections: list[tuple[float, SectionPacket]] = []
        if llm_slices:
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
        else:
            for section in sections:
                summary_score = summaries_by_file.get(
                    section.source_file_id,
                    FileMaterialSummary(),
                ).chapter_affinity.get(chapter_index, 0.0)
                section_score = _section_score_for_chapter(section, terms)
                score = max(float(summary_score or 0.0), section_score)
                if score <= 0 and not terms:
                    score = 0.2
                if score > 0:
                    scored_sections.append((score, section))
            scored_sections.sort(
                key=lambda item: (
                    item[0],
                    item[1].question_block_count,
                    len(item[1].formula_refs),
                    item[1].char_count,
                ),
                reverse=True,
            )
            section_refs = [section.digest_chunk_uid for score, section in scored_sections if score >= 0.18][:12]
            file_ids = list(
                dict.fromkeys(
                    section.source_file_id
                    for _score, section in scored_sections[:16]
                    if section.source_file_id
                )
            )[:8]
            if not file_ids:
                file_ids = [
                    summary.file_id
                    for summary in sorted(summaries, key=lambda item: item.chapter_affinity.get(chapter_index, 0.0), reverse=True)
                    if summary.file_id
                ][:5]
        affinity_items.append(
            SourceAffinityByChapter(
                chapter_index=chapter_index,
                file_ids=file_ids,
                section_refs=section_refs,
                source_slices=llm_slices,
                reason=(
                    "由文件摘要阶段 LLM 对切片目录做章节路由后派生。"
                    if llm_slices
                    else "LLM 未返回可用切片时，由章节标题、目标、required_elements 与切片标题/正文命中规则派生。"
                ),
            )
        )

        if llm_slices:
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
                        evidence_type=source_slice.usage or _evidence_type(text),
                        text=text[:240],
                        chapter_affinity={chapter_index: max(0.35, min(0.98, source_slice.relevance))},
                        confidence=max(0.5, min(0.95, source_slice.relevance + 0.08)),
                        source_title=source_slice.filename or source_slice.section_title,
                        source_span=source_slice.section_ref,
                    )
                )
            continue

        for score, section in scored_sections[:8]:
            fragments = [
                fragment.strip(" -")
                for fragment in _EVIDENCE_SPLIT_RE.split(section.normalized_content or section.preview or "")
                if 18 <= len(fragment.strip()) <= 220
            ]
            if not fragments and section.preview.strip():
                fragments = [section.preview.strip()]
            for fragment in fragments[:2]:
                key = f"{section.digest_chunk_uid}:{fragment[:80]}".casefold()
                if key in evidence_seen:
                    continue
                evidence_seen.add(key)
                evidence_units.append(
                    HighConfidenceEvidenceUnit(
                        evidence_id=f"ch{chapter_index:02d}_{section.digest_chunk_uid}_{len(evidence_units) + 1:03d}",
                        source_ref=f"local://file/{section.source_file_id}/section/{section.digest_chunk_uid}",
                        source_type="local",
                        evidence_type=_evidence_type(fragment),
                        text=fragment[:240],
                        chapter_affinity={chapter_index: max(0.35, min(0.98, score))},
                        confidence=max(0.45, min(0.92, score + 0.15)),
                        source_title=section.source_filename or section.title,
                        source_span=section.digest_chunk_uid,
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
                } or {int(chapters[0].get("chapter_index", 1) or 1): 0.35} if chapters else {}
                evidence_units.append(
                    HighConfidenceEvidenceUnit(
                        evidence_id=f"file{summary.file_id}_ev{len(evidence_units) + 1:03d}",
                        source_ref=f"local://file/{summary.file_id}",
                        source_type="local",
                        evidence_type=_evidence_type(candidate),
                        text=candidate[:240],
                        chapter_affinity=chapter_affinity,
                        confidence=0.5 if summary.fallback_used else 0.65,
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
    fallback = fallback_file_summary(packet, sections=sections, chapters=chapters)
    chapter_titles = [
        str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
        for chapter in chapters
        if str(chapter.get("title") or chapter.get("resolved_title") or "").strip()
    ]
    file_sections = _sections_for_file(sections, packet.file_id)
    section_catalog = build_section_catalog_for_file(packet, sections=file_sections)
    excerpt = str(packet.normalized_content or "").strip()
    if not excerpt.strip():
        return fallback
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
        return fallback
    try:
        summary = response if isinstance(response, FileMaterialSummary) else FileMaterialSummary.model_validate(response)
    except Exception:
        return fallback
    summary.file_id = packet.file_id
    summary.filename = packet.filename
    summary = _normalize_summary_slices(summary, packet=packet, sections=file_sections)
    summary.fallback_used = False
    if not summary.high_value_sections:
        summary.high_value_sections = fallback.high_value_sections
    if not summary.chapter_affinity:
        summary.chapter_affinity = fallback.chapter_affinity
    return summary


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
    return await gather_with_concurrency(
        packets,
        lambda packet: _summarize_one_file(
            packet,
            sections=sections,
            chapters=chapters,
            digest_mode=digest_mode,
            extra_metadata=dict(extra_metadata or {}),
        ),
        limit=min(8, get_llm_concurrency_limit()),
    )


__all__ = ["derive_source_affinity_and_evidence", "fallback_file_summary", "summarize_files"]
