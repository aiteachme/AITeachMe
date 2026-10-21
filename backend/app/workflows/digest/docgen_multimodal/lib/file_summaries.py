"""Route source sections with visual evidence without altering source spans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket
from app.workflows.digest.docgen.lib import file_summaries as text_routing
from app.workflows.digest.docgen.lib.model_policy import (
    DocGenModelStep,
    docgen_completion_kwargs_with_metadata,
)
from app.workflows.digest.docgen.lib.models import FileMaterialSummary
from app.workflows.digest.docgen.lib.source_slices import build_section_catalog_for_file
from app.workflows.digest.docgen.prompts.file_summaries import build_file_summary_messages
from app.workflows.digest.docgen_multimodal.lib.models import VisualEvidence

logger = structlog.get_logger(__name__)

_MAX_IMAGE_SUMMARY_CHARS = 400
_MAX_DETAIL_CHARS = 180
_MAX_IMAGES_PER_SECTION = 12
_MAX_VISUAL_CHARS_PER_SECTION = 6000


def _visual_lines(item: VisualEvidence) -> str:
    lines = [
        f"图片 {item.image_id}（{item.visual_type}；原图文件：{item.asset_filename}）",
        f"图像概述：{item.summary[:_MAX_IMAGE_SUMMARY_CHARS]}",
    ]
    for label, values, limit in (
        ("图中事实", item.key_facts, 5),
        ("图中关系", item.relationships, 4),
        ("图中文字标签", item.labels, 3),
        ("关键概念", item.key_concepts, 3),
        ("图中公式", item.formulas, 3),
        ("图中文字", item.extracted_text, 3),
        ("不确定之处", item.uncertainty_notes, 2),
    ):
        if values:
            lines.append(f"{label}：{'；'.join(value[:_MAX_DETAIL_CHARS] for value in values[:limit])}")
    return "\n".join(lines)


def _evidence_by_section(
    material_context: DigestMaterialContext,
    evidence_items: Sequence[dict[str, Any]],
) -> dict[tuple[str, str], list[VisualEvidence]]:
    valid_sections = {
        (section.source_file_id, section.digest_chunk_uid)
        for section in material_context.section_packets
    }
    grouped: dict[tuple[str, str], list[VisualEvidence]] = {}
    seen: set[str] = set()
    for raw in evidence_items:
        try:
            item = VisualEvidence.model_validate(raw)
        except (TypeError, ValueError):
            logger.warning("docgen_multimodal_invalid_routing_evidence")
            continue
        key = (item.file_id, item.section_ref)
        if key not in valid_sections or item.image_id in seen:
            continue
        seen.add(item.image_id)
        grouped.setdefault(key, []).append(item)
    return grouped


def _visual_context(items: Sequence[VisualEvidence]) -> str:
    if not items:
        return ""
    blocks: list[str] = []
    used_chars = 0
    for item in items[:_MAX_IMAGES_PER_SECTION]:
        block = _visual_lines(item)
        if used_chars + len(block) > _MAX_VISUAL_CHARS_PER_SECTION:
            break
        blocks.append(block)
        used_chars += len(block)
    if not blocks:
        return ""
    return (
        "【本 Section 的图片理解结果；由视觉模型提取，不是原文行号所指的文本；"
        "只用于理解内容及匹配章节，不要将其当作可逐行引用的原文】\n"
        + "\n\n".join(blocks)
        + "\n【图片理解结果结束】"
    )


def _render_sections(
    sections: Sequence[SectionPacket],
    *,
    evidence_by_section: Mapping[tuple[str, str], Sequence[VisualEvidence]],
) -> str:
    blocks: list[str] = []
    for section in sections:
        original = text_routing._render_complete_sections([section])
        visual = _visual_context(
            evidence_by_section.get((section.source_file_id, section.digest_chunk_uid), [])
        )
        if visual and not original:
            original = "\n".join(
                [
                    f"## Section {section.digest_chunk_uid}",
                    f"Title: {section.title or section.header_path}",
                    f"Header path: {section.header_path}",
                    f"Page: {section.page_num or 'unknown'}",
                ]
            )
        if original or visual:
            blocks.append("\n\n".join(part for part in (original, visual) if part))
    return "\n\n".join(blocks)


def _routing_batches(
    sections: Sequence[SectionPacket],
    *,
    evidence_by_section: Mapping[tuple[str, str], Sequence[VisualEvidence]],
) -> list[list[SectionPacket]]:
    batches: list[list[SectionPacket]] = []
    current: list[SectionPacket] = []
    current_chars = 0
    for section in sorted(sections, key=lambda item: int(item.chunk_index or 0)):
        visual_chars = len(
            _visual_context(evidence_by_section.get((section.source_file_id, section.digest_chunk_uid), []))
        )
        section_chars = len(section.normalized_content or "") + visual_chars
        if current and (
            current_chars + section_chars > text_routing._FILE_ROUTING_BATCH_CHARS
            or len(current) >= text_routing._FILE_ROUTING_MAX_SECTIONS_PER_BATCH
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(section)
        current_chars += section_chars
    if current:
        batches.append(current)
    return batches


async def _route_one_batch(
    job: text_routing._FileRoutingJob,
    *,
    chapters: Sequence[Mapping[str, Any]],
    digest_mode: str,
    extra_metadata: Mapping[str, Any],
    evidence_by_section: Mapping[tuple[str, str], Sequence[VisualEvidence]],
) -> text_routing._FileRoutingResult:
    excerpt = _render_sections(job.sections, evidence_by_section=evidence_by_section)
    if not excerpt:
        return text_routing._FileRoutingResult(
            job.packet.file_id,
            text_routing._failed_routing_summary(job.packet, attempted=False),
        )
    try:
        catalog = build_section_catalog_for_file(
            job.packet,
            sections=job.sections,
            max_sections=max(1, len(job.sections)),
        )
        response = await acompletion_with_fallback(
            build_file_summary_messages(
                filename=(
                    job.packet.filename
                    if job.batch_count == 1
                    else f"{job.packet.filename}（第 {job.batch_index}/{job.batch_count} 批）"
                ),
                digest_mode=digest_mode,
                chapter_contracts=text_routing._chapter_contracts(chapters),
                excerpt=excerpt,
                section_catalog=catalog,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.FILE_SUMMARY,
                digest_mode=digest_mode,
                extra_metadata=extra_metadata,
                docgen_stage="route_complete_file_sections_multimodal",
                file_id=job.packet.file_id,
                section_batch_index=job.batch_index,
                section_batch_count=job.batch_count,
                section_count=len(job.sections),
            ),
            response_model=FileMaterialSummary,
        )
        summary = response if isinstance(response, FileMaterialSummary) else FileMaterialSummary.model_validate(response)
        normalized = text_routing._normalize_llm_summary(
            summary, packet=job.packet, sections=job.sections
        )
        spans_by_ref = {
            item["section_ref"]: item
            for item in catalog
        }
        for source_slice in normalized.chapter_slices:
            if (job.packet.file_id, source_slice.section_ref) not in evidence_by_section:
                continue
            original_span = spans_by_ref[source_slice.section_ref]
            source_slice.line_start = original_span["line_start"]
            source_slice.line_end = original_span["line_end"]
        return text_routing._FileRoutingResult(job.packet.file_id, normalized)
    except Exception as exc:  # pragma: no cover - provider integration
        logger.warning(
            "docgen_multimodal_file_routing_failed",
            file_id=job.packet.file_id,
            batch_index=job.batch_index,
            error=str(exc),
        )
        return text_routing._FileRoutingResult(
            job.packet.file_id,
            text_routing._failed_routing_summary(job.packet, attempted=True),
        )


async def summarize_files(
    material_context: DigestMaterialContext,
    *,
    chapters: Sequence[Mapping[str, Any]],
    digest_mode: str,
    visual_evidence_items: Sequence[dict[str, Any]],
    extra_metadata: Mapping[str, Any] | None = None,
) -> list[FileMaterialSummary]:
    """Route original sections using image evidence only in the LLM excerpt."""

    if not visual_evidence_items:
        return await text_routing.summarize_files(
            material_context,
            chapters=chapters,
            digest_mode=digest_mode,
            extra_metadata=extra_metadata,
        )

    evidence_by_section = _evidence_by_section(material_context, visual_evidence_items)
    if not evidence_by_section:
        return await text_routing.summarize_files(
            material_context,
            chapters=chapters,
            digest_mode=digest_mode,
            extra_metadata=extra_metadata,
        )

    packets = list(material_context.source_packets or [])
    sections = list(material_context.section_packets or [])
    jobs: list[text_routing._FileRoutingJob] = []
    for packet in packets:
        batches = _routing_batches(
            text_routing._sections_for_file(sections, packet.file_id),
            evidence_by_section=evidence_by_section,
        ) or [[]]
        jobs.extend(
            text_routing._FileRoutingJob(packet, batch, batch_index, len(batches))
            for batch_index, batch in enumerate(batches, start=1)
        )
    results = await run_llm_tasks(
        jobs,
        lambda job: _route_one_batch(
            job,
            chapters=chapters,
            digest_mode=digest_mode,
            extra_metadata=dict(extra_metadata or {}),
            evidence_by_section=evidence_by_section,
        ),
    )
    by_file: dict[str, list[FileMaterialSummary]] = {}
    for result in results:
        by_file.setdefault(result.file_id, []).append(result.summary)
    return [text_routing._merge_file_results(packet, by_file.get(packet.file_id, [])) for packet in packets]


__all__ = ["summarize_files"]
