"""Merge enhanced chapters and run whole-document review."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.tools.builtin.markdown_processing import prepend_table_of_contents
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.merge_review import build_merge_review_report
from app.workflows.digest.docgen.lib.models import EnhancedChapterDraft
from app.workflows.digest.docgen.lib.publish import build_merged_markdown
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _dedupe_enhanced(chapters: list[EnhancedChapterDraft]) -> list[EnhancedChapterDraft]:
    best: dict[int, EnhancedChapterDraft] = {}
    for chapter in chapters:
        existing = best.get(chapter.chapter_index)
        if existing is None or len(chapter.markdown) >= len(existing.markdown):
            best[chapter.chapter_index] = chapter
    return [best[index] for index in sorted(best)]


def _chapter_metadata(chapter: EnhancedChapterDraft, *, digest_mode: str) -> dict:
    return {
        "chapter_index": chapter.chapter_index,
        "title": chapter.title,
        "resolved_title": chapter.title,
        "markdown": chapter.markdown,
        "summary": chapter.summary,
        "tags": [],
        "digest_mode": digest_mode,
        "source_file_ids": [],
        "sources": list(chapter.sources),
        "source_details": list(chapter.source_details),
        "evidence_ledger": chapter.evidence_ledger.model_dump(mode="json"),
        "quality_signals": chapter.quality_signals.model_dump(mode="json"),
        "asset_ids": list(chapter.asset_ids),
        "practice_ids": list(chapter.practice_ids),
        "warnings": list(chapter.warnings),
        "word_count": len(chapter.markdown),
    }


def build_merge_review_node(*, context: WorkflowContext):
    async def merge_review_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        enhanced = _dedupe_enhanced(
            [
                EnhancedChapterDraft.model_validate(item)
                for item in list(state.get("enhanced_chapter_drafts") or [])
            ]
        )
        if not enhanced:
            return {"error": "没有可发布的增强章节。"}
        expected_chapter_count = len(list(state.get("chapter_tasks") or []))
        review = build_merge_review_report(
            enhanced_chapters=enhanced,
            expected_chapter_count=expected_chapter_count,
            plan_summary=str((state.get("docgen_context") or {}).get("plan_summary") or ""),
        )
        chapter_metadatas = [
            _chapter_metadata(chapter, digest_mode=state.get("digest_mode") or "")
            for chapter in enhanced
        ]
        merged_markdown = prepend_table_of_contents(
            build_merged_markdown(
                chapter_metadatas,
                document_context=dict(state.get("document_context") or {}),
            ),
            min_level=2,
            max_level=4,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="merge_reviewed",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(chapter_metadatas),
            current_stage_description=(
                "整本文档检查完成，准备发布。"
                if review.decision == "publish"
                else f"整本文档检查完成，带 {len(review.issues)} 个 warning 发布。"
            ),
            draft_available=bool(merged_markdown.strip()),
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "merge_reviewed",
                "summary": f"合并检查完成，决策：{review.decision}，问题数：{len(review.issues)}。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="merge_reviewed",
            payload={
                "chapter_count": len(chapter_metadatas),
                "decision": review.decision,
                "issue_count": len(review.issues),
            },
        )
        return {
            "chapter_metadatas": chapter_metadatas,
            "merged_markdown": merged_markdown,
            "enriched_markdown": merged_markdown,
            "merge_review_report": review.model_dump(mode="json"),
            "merge_review_ms": elapsed_ms,
        }

    return merge_review_node


__all__ = ["build_merge_review_node"]
