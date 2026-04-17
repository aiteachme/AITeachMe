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
from app.workflows.digest.docgen.lib.models import FileMaterialSummary, clean_string_list
from app.workflows.digest.docgen.prompts.file_summaries import build_file_summary_messages

logger = structlog.get_logger(__name__)

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_FORMULA_RE = re.compile(r"\$\$?([^$\n]{2,120})\$\$?", re.DOTALL)
_QUESTION_RE = re.compile(r"(例题|习题|选择题|填空题|简答题|证明题|计算题|真题|练习)")


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
            max_tokens=1200,
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


__all__ = ["fallback_file_summary", "summarize_files"]
