"""Project routed VisualEvidence into chapter-local text retrieval inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket
from app.workflows.digest.docgen.lib.models import ChapterGenerationTask, ChapterSourceSlice
from app.workflows.digest.docgen_multimodal.lib.models import VisualEvidence

logger = structlog.get_logger(__name__)

_MAX_VISUALS_PER_CHAPTER = 8
_MAX_VISUAL_CHARS_PER_CHAPTER = 6000
_MAX_VISUAL_CHARS_PER_IMAGE = 1400
_MAX_LIST_ITEMS = 5
_MAX_ITEM_CHARS = 180


@dataclass(frozen=True)
class ChapterVisualContext:
    state: dict[str, Any]
    evidence: list[VisualEvidence]
    urls_by_image_id: dict[str, str]


def visual_source_ref(item: VisualEvidence) -> str:
    return f"{item.section_ref}/image/{item.image_id}"


def visual_source_url(item: VisualEvidence) -> str:
    return f"local://file/{item.file_id}/section/{visual_source_ref(item)}"


def _list_line(label: str, values: list[str]) -> str:
    cleaned = [str(value).strip()[:_MAX_ITEM_CHARS] for value in values if str(value).strip()]
    return f"- {label}：{'；'.join(cleaned[:_MAX_LIST_ITEMS])}" if cleaned else ""


def render_chapter_visual_evidence(item: VisualEvidence) -> str:
    """Render reusable image facts as a bounded, source-addressable text block."""

    lines = [
        "## 本章视觉证据",
        f"- 图片 ID：{item.image_id}",
        f"- 原始 Section：{item.section_ref}",
        f"- 图片文件：{item.asset_filename}",
        f"- 图片类型：{item.visual_type}",
        f"- 图像概述：{item.summary[:420]}",
        _list_line("图中事实", item.key_facts),
        _list_line("图中关系", item.relationships),
        _list_line("文字标签", item.labels),
        _list_line("关键概念", item.key_concepts),
        _list_line("图中公式", item.formulas),
        _list_line("可见文字", item.extracted_text),
        _list_line("不确定之处", item.uncertainty_notes),
        f"- 置信度：{item.confidence:.2f}",
        "- 使用约束：只使用上述可见事实；不确定之处不得写成确定结论。",
    ]
    return "\n".join(line for line in lines if line)[:_MAX_VISUAL_CHARS_PER_IMAGE].rstrip()


def _parse_evidence(raw_items: list[dict[str, Any]]) -> list[VisualEvidence]:
    parsed: list[VisualEvidence] = []
    seen: set[str] = set()
    for raw in raw_items:
        try:
            item = VisualEvidence.model_validate(raw)
        except (TypeError, ValueError):
            logger.warning("docgen_multimodal_invalid_chapter_visual_evidence")
            continue
        if item.image_id in seen:
            continue
        seen.add(item.image_id)
        parsed.append(item)
    return parsed


def _evidence_for_task(
    task: ChapterGenerationTask,
    evidence_items: list[VisualEvidence],
) -> list[VisualEvidence]:
    routed_pairs = {
        (source_slice.file_id, source_slice.section_ref)
        for source_slice in task.source_slices
        if source_slice.file_id and source_slice.section_ref
    }
    if not routed_pairs:
        return []
    relevance_by_pair = {
        (source_slice.file_id, source_slice.section_ref): source_slice.relevance
        for source_slice in task.source_slices
    }
    candidates = [
        item
        for item in evidence_items
        if (item.file_id, item.section_ref) in routed_pairs
    ]
    candidates.sort(
        key=lambda item: (
            -float(relevance_by_pair.get((item.file_id, item.section_ref), 0.0)),
            -float(item.teaching_value),
            -float(item.confidence),
            item.image_id,
        )
    )
    selected: list[VisualEvidence] = []
    used_chars = 0
    for item in candidates:
        rendered_chars = len(render_chapter_visual_evidence(item))
        if selected and used_chars + rendered_chars > _MAX_VISUAL_CHARS_PER_CHAPTER:
            continue
        selected.append(item)
        used_chars += rendered_chars
        if len(selected) >= _MAX_VISUALS_PER_CHAPTER:
            break
    return selected


def build_chapter_visual_context(state: dict[str, Any]) -> ChapterVisualContext:
    """Clone branch inputs and add image evidence as independent local sections."""

    raw_shared_inputs = state.get("shared_inputs")
    raw_task = state.get("chapter_task")
    if raw_shared_inputs is None or raw_task is None:
        return ChapterVisualContext(dict(state), [], {})
    try:
        material_context = (
            raw_shared_inputs
            if isinstance(raw_shared_inputs, DigestMaterialContext)
            else DigestMaterialContext.model_validate(raw_shared_inputs)
        )
        task = ChapterGenerationTask.model_validate(raw_task)
    except (TypeError, ValueError):
        return ChapterVisualContext(dict(state), [], {})

    selected = _evidence_for_task(
        task,
        _parse_evidence(list(state.get("visual_evidence_items") or [])),
    )
    if not selected:
        return ChapterVisualContext(dict(state), [], {})

    sections_by_ref = {
        section.digest_chunk_uid: section
        for section in material_context.section_packets
    }
    slices_by_pair: dict[tuple[str, str], ChapterSourceSlice] = {
        (source_slice.file_id, source_slice.section_ref): source_slice
        for source_slice in task.source_slices
    }
    synthetic_sections: list[SectionPacket] = []
    synthetic_slices: list[ChapterSourceSlice] = []
    urls_by_image_id: dict[str, str] = {}
    max_chunk_index = max(
        (int(section.chunk_index or 0) for section in material_context.section_packets),
        default=0,
    )
    accepted: list[VisualEvidence] = []
    for offset, item in enumerate(selected, start=1):
        parent = sections_by_ref.get(item.section_ref)
        source_slice = slices_by_pair.get((item.file_id, item.section_ref))
        if parent is None or source_slice is None or parent.source_file_id != item.file_id:
            continue
        text = render_chapter_visual_evidence(item)
        section_ref = visual_source_ref(item)
        title = f"图片证据：{item.asset_filename}"
        synthetic_sections.append(
            SectionPacket(
                digest_chunk_uid=section_ref,
                source_file_id=item.file_id,
                source_filename=item.source_filename,
                chunk_index=max_chunk_index + offset,
                page_num=parent.page_num,
                title=title,
                header_path=f"{parent.header_path} / {title}".strip(" /"),
                level=max(1, int(parent.level or 1) + 1),
                normalized_content=text,
                preview=text[:320],
                char_count=len(text),
                formula_refs=list(item.formulas),
                image_refs=[item.asset_filename],
            )
        )
        synthetic_slices.append(
            ChapterSourceSlice(
                chapter_index=task.chapter_index,
                file_id=item.file_id,
                filename=item.source_filename,
                section_ref=section_ref,
                section_title=title,
                header_path=f"{parent.header_path} / {title}".strip(" /"),
                relevance=max(0.5, float(source_slice.relevance)),
                usage="visual_evidence",
                reason="该图片属于本章已路由的资料 Section，可补充正文未表达的视觉事实。",
                summary=item.summary[:180],
            )
        )
        urls_by_image_id[item.image_id] = visual_source_url(item)
        accepted.append(item)

    if not synthetic_sections:
        return ChapterVisualContext(dict(state), [], {})

    # Put bounded visual evidence first so a long source section cannot consume
    # the entire priority-context budget before the image facts are included.
    enriched_task = task.model_copy(
        update={
            "source_slices": [*synthetic_slices, *task.source_slices],
            "priority_section_refs": [
                *[item.section_ref for item in synthetic_slices],
                *task.priority_section_refs,
            ],
        }
    )
    enriched_material = material_context.model_copy(
        update={
            "material_sections": [
                *material_context.section_packets,
                *synthetic_sections,
            ]
        }
    )
    enriched_state = dict(state)
    enriched_state["shared_inputs"] = enriched_material
    enriched_state["chapter_task"] = enriched_task.model_dump(mode="json")
    return ChapterVisualContext(enriched_state, accepted, urls_by_image_id)


def annotate_visual_sources(
    result: dict[str, Any],
    visual_context: ChapterVisualContext,
) -> dict[str, Any]:
    """Mark synthetic source records in the multimodal chapter node output."""

    if not visual_context.evidence:
        return result
    evidence_by_url = {
        visual_context.urls_by_image_id[item.image_id]: item
        for item in visual_context.evidence
    }
    updated = dict(result)

    def annotate_details(raw_details: list[dict[str, Any]]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for raw in raw_details:
            item = dict(raw)
            evidence = evidence_by_url.get(str(item.get("url") or ""))
            if evidence is not None:
                item.update(
                    {
                        "source": "docgen_visual_evidence",
                        "source_ref": evidence.image_id,
                        "file_id": evidence.file_id,
                        "section_ref": evidence.section_ref,
                        "image_id": evidence.image_id,
                        "visual_type": evidence.visual_type,
                        "confidence": evidence.confidence,
                    }
                )
            details.append(item)
        return details

    drafts = []
    for raw_draft in list(updated.get("chapter_drafts") or []):
        draft = dict(raw_draft)
        draft["source_details"] = annotate_details(list(draft.get("source_details") or []))
        draft["visual_evidence_count"] = len(visual_context.evidence)
        drafts.append(draft)
    updated["chapter_drafts"] = drafts

    traces = []
    for raw_trace in list(updated.get("research_traces") or []):
        trace = dict(raw_trace)
        trace["opened_contexts"] = annotate_details(list(trace.get("opened_contexts") or []))
        trace["budget_used"] = {
            **dict(trace.get("budget_used") or {}),
            "visual_evidence_count": len(visual_context.evidence),
        }
        traces.append(trace)
    updated["research_traces"] = traces

    ledgers = []
    for raw_ledger in list(updated.get("evidence_ledgers") or []):
        ledger = dict(raw_ledger)
        items = []
        for raw_item in list(ledger.get("items") or []):
            item = dict(raw_item)
            evidence = evidence_by_url.get(str(item.get("source_ref") or ""))
            if evidence is not None:
                item.update(
                    {
                        "kind": "visual",
                        "source_span": evidence.image_id,
                        "confidence": evidence.confidence,
                    }
                )
            items.append(item)
        ledger["items"] = items
        ledgers.append(ledger)
    updated["evidence_ledgers"] = ledgers
    return updated


__all__ = [
    "ChapterVisualContext",
    "annotate_visual_sources",
    "build_chapter_visual_context",
    "render_chapter_visual_evidence",
    "visual_source_ref",
    "visual_source_url",
]
