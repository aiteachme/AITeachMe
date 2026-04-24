"""Review enhanced DocGen content before merge."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    update_knowledge_build_status,
    upsert_knowledge_build_chapter_preview,
    upsert_knowledge_build_chapter_progress,
)
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.chapter_review import review_chapter
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ClaimEvidenceMap,
    ClaimLedger,
    ConflictReport,
    DocumentBackbone,
    EnhancedChapterDraft,
    ReviewAction,
    ReviewedChapterDraft,
)
from app.workflows.digest.docgen.nodes.common import extract_markdown_preview_headings, publish_docgen_progress
from app.workflows.digest.docgen.lib.quality import review_document_consistency
from app.workflows.digest.docgen.state import DocGenState


def _review_decision(actions: list[ReviewAction], *, document_issue_count: int) -> str:
    blocking_types = {"section_patch", "evidence_patch", "regenerate_chapter", "re_dispatch", "rebuild_backbone"}
    has_blocking_action = any(
        action.action_type in blocking_types and action.severity in {"warning", "error"}
        for action in actions
    )
    has_error_action = any(action.severity == "error" for action in actions)
    if has_error_action:
        return "fail"
    if has_blocking_action:
        return "needs_repair"
    if actions or document_issue_count:
        return "publish_with_warnings"
    return "good"


def _by_chapter(model_cls, items: list[dict]) -> dict[int, object]:
    return {
        int(item.get("chapter_index", 0) or 0): model_cls.model_validate(item)
        for item in items
    }


def build_review_chapter_node(*, context: WorkflowContext):
    """构建单章复核节点。

    该节点通过 LangGraph Send 按章 fan-out 运行。每个分支只复核一个
    EnhancedChapterDraft，并输出单章 ReviewedDraft、ReviewReport 和
    ReviewAction，随后由 reducers fan-in 到整本一致性节点。
    """

    async def review_chapter_node(state: DocGenState) -> dict:
        """复核一个增强章节。"""

        started_at = perf_counter()
        draft = EnhancedChapterDraft.model_validate(state["enhanced_chapter_draft"])
        tasks_by_chapter = _by_chapter(ChapterGenerationTask, list(state.get("chapter_tasks") or []))
        claim_ledgers_by_chapter = _by_chapter(ClaimLedger, list(state.get("claim_ledgers") or []))
        claim_maps_by_chapter = _by_chapter(ClaimEvidenceMap, list(state.get("claim_evidence_maps") or []))
        conflict_reports_by_chapter = _by_chapter(ConflictReport, list(state.get("conflict_reports") or []))

        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="reviewing_content",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在并行复核章节覆盖、证据支撑和写作质量。",
        )
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={"chapter_index": draft.chapter_index, "title": draft.title, "status": "reviewing"},
        )
        upsert_knowledge_build_chapter_preview(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_preview={
                "chapter_index": draft.chapter_index,
                "title": draft.title,
                "status": "reviewing",
            },
        )
        reviewed, report, actions = await review_chapter(
            draft=draft,
            task=tasks_by_chapter.get(draft.chapter_index),
            claim_ledger=claim_ledgers_by_chapter.get(draft.chapter_index),
            claim_evidence_map=claim_maps_by_chapter.get(draft.chapter_index),
            conflict_report=conflict_reports_by_chapter.get(draft.chapter_index),
            digest_mode=state.get("digest_mode") or "",
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={"chapter_index": draft.chapter_index, "title": draft.title, "status": "reviewed"},
        )
        upsert_knowledge_build_chapter_preview(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_preview={
                "chapter_index": draft.chapter_index,
                "title": reviewed.title,
                "status": "reviewed",
                "excerpt": reviewed.markdown.strip(),
                "latest_headings": extract_markdown_preview_headings(reviewed.markdown),
                "word_count": count_words(reviewed.markdown),
                "source_count": len(reviewed.source_details),
            },
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "chapter_reviewed",
                "chapter_index": draft.chapter_index,
                "title": reviewed.title,
                "summary": f"{reviewed.title} 内容复核完成，发现 {len(actions)} 条回流建议。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_reviewed",
            payload={
                "chapter_index": draft.chapter_index,
                "title": reviewed.title,
                "passed": report.passed,
                "review_action_count": len(actions),
                "coverage_score": report.coverage_score,
                "evidence_support_score": report.evidence_support_score,
            },
        )
        return {
            "reviewed_chapter_draft_items": [reviewed.model_dump(mode="json")],
            "chapter_review_report_items": [report.model_dump(mode="json")],
            "review_action_items": [item.model_dump(mode="json") for item in actions],
            "review_ms": elapsed_ms,
            "llm_calls_total": 1,
        }

    return review_chapter_node


def build_document_consistency_review_node(*, context: WorkflowContext):
    """构建整本一致性复核节点。

    所有章节复核 fan-in 后运行，只做跨章术语、标题、章节数量和整体
    风格一致性判断，不再发起章节级 LLM 调用。
    """

    async def document_consistency_review_node(state: DocGenState) -> dict:
        """汇总章节 review 并生成 review_decision。"""

        started_at = perf_counter()
        reviewed = [
            ReviewedChapterDraft.model_validate(item)
            for item in sorted(
                list(state.get("reviewed_chapter_draft_items") or []),
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        if not reviewed:
            return {"error": "没有可做整本一致性复核的章节。"}
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        actions = [
            ReviewAction.model_validate(item)
            for item in list(state.get("review_action_items") or [])
        ]
        consistency_report = review_document_consistency(
            reviewed_chapters=reviewed,
            document_backbone=document_backbone,
            expected_chapter_count=len(list(state.get("chapter_tasks") or [])),
        )
        review_decision = _review_decision(
            actions,
            document_issue_count=len(consistency_report.issues),
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="content_reviewed",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"内容复核完成，决策 {review_decision}，记录 {len(actions)} 条回流建议。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "content_reviewed",
                "summary": f"章节复核和整本一致性检查完成，决策 {review_decision}，回流建议 {len(actions)} 条。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="content_reviewed",
            payload={
                "chapter_count": len(reviewed),
                "review_parallelism": min(6, len(reviewed)),
                "review_decision": review_decision,
                "review_action_count": len(actions),
                "document_issue_count": len(consistency_report.issues),
            },
        )
        return {
            "reviewed_chapter_drafts": [item.model_dump(mode="json") for item in reviewed],
            "chapter_review_reports": list(state.get("chapter_review_report_items") or []),
            "review_actions": [item.model_dump(mode="json") for item in actions],
            "document_consistency_report": consistency_report.model_dump(mode="json"),
            "review_decision": review_decision,
            "review_ms": elapsed_ms,
        }

    return document_consistency_review_node


__all__ = ["build_document_consistency_review_node", "build_review_chapter_node"]
