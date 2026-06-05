"""DocGen source-slice cataloging and context hydration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.shared.infra.knowledge.source_text import extract_line_span, line_span_for_excerpt, number_lines
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket

SECTION_CATALOG_MAX_PREVIEW_CHARS = 320


@dataclass(frozen=True)
class HydratedSourceContext:
    """Prompt-ready context built from LLM-selected source slices."""

    text: str
    sources: list[str]
    source_details: list[dict[str, Any]]

    @property
    def local_source_count(self) -> int:
        return len(self.source_details)


def _line_span_for_section(packet: SourcePacket, section: SectionPacket) -> tuple[int | None, int | None]:
    span = line_span_for_excerpt(packet.normalized_content, section.normalized_content)
    if span is None:
        return None, None
    return span.start_line, span.end_line


def _line_spans_by_section_ref(
    packet: SourcePacket,
    *,
    sections: list[SectionPacket],
) -> dict[str, tuple[int | None, int | None]]:
    spans: dict[str, tuple[int | None, int | None]] = {}
    cursor = 0
    for section in sorted(sections, key=lambda item: int(item.chunk_index or 0)):
        span = line_span_for_excerpt(
            packet.normalized_content,
            section.normalized_content,
            start_offset=cursor,
        )
        if span is None:
            span = line_span_for_excerpt(packet.normalized_content, section.normalized_content)
        if span is None:
            spans[section.digest_chunk_uid] = (None, None)
            continue
        spans[section.digest_chunk_uid] = (span.start_line, span.end_line)
        cursor = max(cursor, span.end_offset)
    return spans


def build_section_catalog_for_file(
    packet: SourcePacket,
    *,
    sections: list[SectionPacket],
    max_sections: int = 80,
) -> list[dict[str, Any]]:
    """Build a compact section catalog for LLM chapter routing."""

    catalog: list[dict[str, Any]] = []
    line_spans = _line_spans_by_section_ref(packet, sections=sections)
    for section in sections[: max(1, int(max_sections))]:
        start_line, end_line = line_spans.get(section.digest_chunk_uid, (None, None))
        catalog.append(
            {
                "section_ref": section.digest_chunk_uid,
                "file_id": packet.file_id,
                "filename": packet.filename,
                "title": section.title,
                "header_path": section.header_path,
                "line_start": start_line,
                "line_end": end_line,
                "page_num": section.page_num,
                "char_count": section.char_count,
                "formula_count": len(section.formula_refs),
                "question_block_count": section.question_block_count,
                "preview": (section.preview or section.normalized_content[:SECTION_CATALOG_MAX_PREVIEW_CHARS]).strip()[
                    :SECTION_CATALOG_MAX_PREVIEW_CHARS
                ],
            }
        )
    return catalog


def index_line_spans_by_section_ref(material_context: DigestMaterialContext) -> dict[str, tuple[int | None, int | None]]:
    sources_by_file = index_sources_by_file_id(material_context)
    sections_by_file: dict[str, list[SectionPacket]] = {}
    for section in list(material_context.section_packets or []):
        sections_by_file.setdefault(section.source_file_id, []).append(section)

    spans: dict[str, tuple[int | None, int | None]] = {}
    for file_id, sections in sections_by_file.items():
        packet = sources_by_file.get(file_id)
        if packet is None:
            continue
        spans.update(_line_spans_by_section_ref(packet, sections=sections))
    return spans


def index_sections_by_ref(material_context: DigestMaterialContext) -> dict[str, SectionPacket]:
    return {
        section.digest_chunk_uid: section
        for section in list(material_context.section_packets or [])
        if section.digest_chunk_uid
    }


def index_sources_by_file_id(material_context: DigestMaterialContext) -> dict[str, SourcePacket]:
    return {
        packet.file_id: packet
        for packet in list(material_context.source_packets or [])
        if packet.file_id
    }


def _source_url(*, file_id: str, section_ref: str, start_line: int | None, end_line: int | None) -> str:
    suffix = f"#L{start_line}-L{end_line}" if start_line and end_line else ""
    return f"local://file/{file_id}/section/{section_ref}{suffix}"


def _slice_value(slice_item: Any, key: str, default: Any = None) -> Any:
    if isinstance(slice_item, dict):
        return slice_item.get(key, default)
    return getattr(slice_item, key, default)


def build_priority_source_context(
    material_context: DigestMaterialContext | None,
    source_slices: list[Any],
    *,
    max_total_chars: int = 3600,
    max_excerpt_chars: int = 900,
) -> HydratedSourceContext:
    """Hydrate LLM-selected slices into exact line excerpts plus summaries."""

    if material_context is None or not source_slices:
        return HydratedSourceContext(text="", sources=[], source_details=[])

    sources_by_file = index_sources_by_file_id(material_context)
    sections_by_ref = index_sections_by_ref(material_context)
    line_spans_by_ref = index_line_spans_by_section_ref(material_context)
    blocks: list[str] = []
    details: list[dict[str, Any]] = []
    sources: list[str] = []
    used_chars = 0
    seen: set[str] = set()

    for raw_slice in source_slices:
        section_ref = str(_slice_value(raw_slice, "section_ref", "") or "").strip()
        file_id = str(_slice_value(raw_slice, "file_id", "") or "").strip()
        if not section_ref:
            continue
        section = sections_by_ref.get(section_ref)
        if section is None:
            continue
        if not file_id:
            file_id = section.source_file_id
        packet = sources_by_file.get(file_id)
        if packet is None:
            continue
        dedupe_key = f"{file_id}:{section_ref}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        start_line = int(_slice_value(raw_slice, "line_start", 0) or 0) or None
        end_line = int(_slice_value(raw_slice, "line_end", 0) or 0) or None
        if not start_line or not end_line:
            start_line, end_line = line_spans_by_ref.get(section_ref, (None, None))
        if not start_line or not end_line:
            start_line, end_line = _line_span_for_section(packet, section)
        if start_line and end_line:
            excerpt = extract_line_span(
                packet.normalized_content,
                start_line=start_line,
                end_line=end_line,
                context_lines=0,
                max_chars=max_excerpt_chars,
            )
        else:
            excerpt = section.normalized_content[:max_excerpt_chars].strip()

        summary = str(_slice_value(raw_slice, "summary", "") or "").strip()
        reason = str(_slice_value(raw_slice, "reason", "") or "").strip()
        title = str(_slice_value(raw_slice, "section_title", "") or section.title or section.header_path).strip()
        line_label = f"L{start_line}-L{end_line}" if start_line and end_line else "line:unknown"
        block_lines = [
            f"### 来源切片：{packet.filename} / {title} ({line_label})",
        ]
        if summary:
            block_lines.append(f"- 切片摘要：{summary}")
        if reason:
            block_lines.append(f"- 章节用途：{reason}")
        if excerpt:
            block_lines.extend(["", "原文摘录：", number_lines(excerpt, start_line=start_line or 1)])
        block = "\n".join(block_lines).strip()
        if not block:
            continue
        if used_chars + len(block) > max(1200, int(max_total_chars)) and blocks:
            break
        used_chars += len(block)

        url = _source_url(file_id=file_id, section_ref=section_ref, start_line=start_line, end_line=end_line)
        sources.append(url)
        details.append(
            {
                "url": url,
                "title": f"{packet.filename} / {title}",
                "source": "docgen_source_slice",
                "score": float(_slice_value(raw_slice, "relevance", 0.8) or 0.8),
                "source_ref": section_ref,
                "file_id": file_id,
                "line_start": start_line,
                "line_end": end_line,
                "summary": summary,
                "snippet": excerpt[:500],
            }
        )
        blocks.append(block)

    if not blocks:
        return HydratedSourceContext(text="", sources=[], source_details=[])
    text = "## LLM 预选的本地资料切片\n\n" + "\n\n".join(blocks)
    return HydratedSourceContext(text=text.strip(), sources=sources, source_details=details)


__all__ = [
    "HydratedSourceContext",
    "build_priority_source_context",
    "build_section_catalog_for_file",
    "index_line_spans_by_section_ref",
    "index_sections_by_ref",
    "index_sources_by_file_id",
]
