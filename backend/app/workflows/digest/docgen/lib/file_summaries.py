"""DocGen-oriented source file summaries."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib.models import (
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    SourceAffinityByChapter,
    clean_string_list,
)
from app.workflows.digest.docgen.prompts.file_summaries import build_file_summary_messages

logger = structlog.get_logger(__name__)

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_FORMULA_RE = re.compile(r"\$\$?([^$\n]{2,120})\$\$?", re.DOTALL)
_QUESTION_RE = re.compile(r"(例题|习题|选择题|填空题|简答题|证明题|计算题|真题|练习)")
_EVIDENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s+|\n+")


def _sample_excerpt(packet: SourcePacket, *, max_chars: int = 18000) -> str:
    text = str(packet.normalized_content or "").strip()
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.55)]
    middle_start = max(0, int(len(text) * 0.45))
    middle = text[middle_start : middle_start + int(max_chars * 0.25)]
    tail = text[-int(max_chars * 0.2) :]
    return "\n\n".join([head, "\n[...中间抽样...]\n", middle, "\n[...末尾抽样...]\n", tail])


def _sections_for_file(sections: Sequence[SectionPacket], file_id: int) -> list[SectionPacket]:
    return [section for section in sections if int(section.source_file_id or 0) == file_id]


def fallback_file_summary(
    packet: SourcePacket,
    *,
    sections: Sequence[SectionPacket],
    chapters: Sequence[Mapping[str, Any]],
) -> FileMaterialSummary:
    file_sections = _sections_for_file(sections, int(packet.file_id))
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
        file_id=int(packet.file_id),
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
    """Derive stable rule-based source signals for the document backbone."""

    sections = list(material_context.section_packets or [])
    summaries_by_file = {int(summary.file_id): summary for summary in summaries if int(summary.file_id or 0) > 0}
    affinity_items: list[SourceAffinityByChapter] = []
    evidence_units: list[HighConfidenceEvidenceUnit] = []
    evidence_seen: set[str] = set()

    for index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        terms = _chapter_terms(chapter)
        scored_sections: list[tuple[float, SectionPacket]] = []
        for section in sections:
            summary_score = summaries_by_file.get(int(section.source_file_id or 0), FileMaterialSummary()).chapter_affinity.get(chapter_index, 0.0)
            section_score = _section_score_for_chapter(section, terms)
            score = max(float(summary_score or 0.0), section_score)
            if score <= 0 and not terms:
                score = 0.2
            if score > 0:
                scored_sections.append((score, section))
        scored_sections.sort(key=lambda item: (item[0], item[1].question_block_count, len(item[1].formula_refs), item[1].char_count), reverse=True)
        section_refs = [section.digest_chunk_uid for score, section in scored_sections if score >= 0.18][:12]
        file_ids = list(dict.fromkeys(int(section.source_file_id) for _score, section in scored_sections[:16] if int(section.source_file_id or 0) > 0))[:8]
        if not file_ids:
            file_ids = [
                summary.file_id
                for summary in sorted(summaries, key=lambda item: item.chapter_affinity.get(chapter_index, 0.0), reverse=True)
                if summary.file_id > 0
            ][:5]
        affinity_items.append(
            SourceAffinityByChapter(
                chapter_index=chapter_index,
                file_ids=file_ids,
                section_refs=section_refs,
                reason="由章节标题、目标、required_elements 与切片标题/正文命中规则派生。",
            )
        )

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
    excerpt = _sample_excerpt(packet)
    if not excerpt.strip():
        return fallback
    try:
        response = await acompletion_with_fallback(
            build_file_summary_messages(
                filename=packet.filename,
                digest_mode=digest_mode,
                chapter_titles=chapter_titles,
                excerpt=excerpt,
            ),
            task_type=TaskType.DOCGEN_LIGHT,
            model="light",
            response_model=FileMaterialSummary,
            temperature=0.1,
            max_tokens=5000,
            extra_metadata={
                "docgen_stage": "summarize_file",
                "file_id": packet.file_id,
                **dict(extra_metadata),
            },
        )
    except Exception as exc:
        logger.warning("docgen_file_summary_failed", file_id=packet.file_id, error=str(exc))
        return fallback
    try:
        summary = response if isinstance(response, FileMaterialSummary) else FileMaterialSummary.model_validate(response)
    except Exception:
        return fallback
    summary.file_id = int(packet.file_id)
    summary.filename = packet.filename
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
    return list(
        await asyncio.gather(
            *(
                _summarize_one_file(
                    packet,
                    sections=sections,
                    chapters=chapters,
                    digest_mode=digest_mode,
                    extra_metadata=dict(extra_metadata or {}),
                )
                for packet in packets
            )
        )
    )


__all__ = ["derive_source_affinity_and_evidence", "fallback_file_summary", "summarize_files"]
