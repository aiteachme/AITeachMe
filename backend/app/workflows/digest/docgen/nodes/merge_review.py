"""Merge enhanced chapters and run whole-document review."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.tools.builtin.markdown_processing import count_words, prepend_table_of_contents
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


def _chapter_metadata(
    chapter: EnhancedChapterDraft,
    *,
    digest_mode: str,
    claim_ledger: dict | None = None,
    claim_evidence_map: dict | None = None,
    conflict_report: dict | None = None,
    chapter_review_report: dict | None = None,
) -> dict:
    # 这里是发布 manifest 的结构化收口，不改写正文；内容修复必须发生在更早的 review/repair 阶段。
    source_scope = dict(chapter.source_scope or {})
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
        "source_scope": source_scope,
        "local_hits": int(source_scope.get("local_hits", 0) or 0),
        "web_hits": int(source_scope.get("web_hits", 0) or 0),
        "query_count": int(source_scope.get("query_count", 0) or 0),
        "read_url_count": int(source_scope.get("read_url_count", 0) or 0),
        "document_count": int(source_scope.get("document_count", 0) or 0),
        "fallback_used": bool(chapter.fallback_used),
        "evidence_ledger": chapter.evidence_ledger.model_dump(mode="json"),
        "claim_ledger_ref": chapter.claim_ledger_ref,
        "claim_ledger": dict(claim_ledger or {}),
        "claim_evidence_map": dict(claim_evidence_map or {}),
        "conflict_report": dict(conflict_report or {}),
        "chapter_review_report": dict(chapter_review_report or {}),
        "conflict_warning_refs": list(chapter.conflict_warning_refs),
        "quality_signals": chapter.quality_signals.model_dump(mode="json"),
        "asset_ids": list(chapter.asset_ids),
        "practice_ids": list(chapter.practice_ids),
        "warnings": list(chapter.warnings),
        "word_count": count_words(chapter.markdown),
    }


def build_merge_review_node(*, context: WorkflowContext):
    """构建章节合并和发布前检查节点。

    这里不再做重知识复核，只负责把 reviewed/enhanced drafts 按章节收口、
    生成发布 metadata、合并整本 Markdown，并记录发布前完整性问题。
    """

    async def merge_review_node(state: DocGenState) -> dict:
        """合并章节并生成 merge review report。"""

        started_at = perf_counter()
        raw_chapters = list(state.get("reviewed_chapter_drafts") or []) or list(state.get("enhanced_chapter_drafts") or [])
        enhanced = _dedupe_enhanced(
            [
                EnhancedChapterDraft.model_validate(item)
                for item in raw_chapters
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
        claim_ledgers_by_chapter = {
            int(item.get("chapter_index", 0) or 0): item
            for item in list(state.get("claim_ledgers") or [])
        }
        claim_maps_by_chapter = {
            int(item.get("chapter_index", 0) or 0): item
            for item in list(state.get("claim_evidence_maps") or [])
        }
        conflict_reports_by_chapter = {
            int(item.get("chapter_index", 0) or 0): item
            for item in list(state.get("conflict_reports") or [])
        }
        review_reports_by_chapter = {
            int(item.get("chapter_index", 0) or 0): item
            for item in list(state.get("chapter_review_reports") or [])
        }
        chapter_metadatas = []
        for chapter in enhanced:
            chapter_metadatas.append(
                _chapter_metadata(
                    chapter,
                    digest_mode=state.get("digest_mode") or "",
                    claim_ledger=claim_ledgers_by_chapter.get(chapter.chapter_index),
                    claim_evidence_map=claim_maps_by_chapter.get(chapter.chapter_index),
                    conflict_report=conflict_reports_by_chapter.get(chapter.chapter_index),
                    chapter_review_report=review_reports_by_chapter.get(chapter.chapter_index),
                )
            )
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
