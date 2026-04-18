"""Conflict reporting helpers for DocGen chapters."""

from __future__ import annotations

from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ConflictItem,
    ConflictReport,
    DocumentBackbone,
    EvidenceLedger,
    clean_string_list,
)


def resolve_conflicts_for_chapter(
    *,
    task: ChapterGenerationTask,
    evidence_ledger: EvidenceLedger,
    document_backbone: DocumentBackbone | None = None,
) -> ConflictReport:
    items: list[ConflictItem] = []
    backbone = document_backbone or DocumentBackbone()
    unresolved_count = 0
    for index, confusion in enumerate(backbone.confusion_map, start=1):
        if confusion.target_chapters and task.chapter_index not in confusion.target_chapters:
            continue
        topic = confusion.topic or confusion.contrast
        if not topic:
            continue
        if topic in task.confusion_targets or topic in task.required_elements or not confusion.target_chapters:
            items.append(
                ConflictItem(
                    conflict_id=f"ch{task.chapter_index:02d}_conf_{index:03d}",
                    chapter_index=task.chapter_index,
                    conflict_type="confusion_target",
                    severity="info",
                    detail=f"本章需要显式处理易混点：{topic}",
                    resolution=confusion.resolution_hint or "正文中说明边界和判断条件。",
                    source_refs=[],
                )
            )
    low_confidence = [
        item
        for item in evidence_ledger.items
        if item.confidence < task.evidence_support_threshold and item.source_type == "generated"
    ]
    if low_confidence:
        unresolved_count += len(low_confidence)
        items.append(
            ConflictItem(
                conflict_id=f"ch{task.chapter_index:02d}_low_evidence",
                chapter_index=task.chapter_index,
                conflict_type="low_evidence_support",
                severity="warning",
                detail="部分主张缺少可靠资料支撑，章节需要使用不确定性表达。",
                resolution="避免宣称为真题、权威结论或材料明确内容；保留降级说明。",
                source_refs=clean_string_list([item.source_ref for item in low_confidence], limit=8),
            )
        )
    return ConflictReport(
        chapter_index=task.chapter_index,
        items=items,
        unresolved_count=unresolved_count,
    )


__all__ = ["resolve_conflicts_for_chapter"]
