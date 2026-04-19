"""Review enhanced DocGen content before merge."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.chapter_review import review_chapter
from app.workflows.digest.docgen.lib.document_consistency import review_document_consistency
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    ClaimEvidenceMap,
    ClaimLedger,
    ConflictReport,
    DocumentBackbone,
    EnhancedChapterDraft,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _review_decision(actions: list, *, document_issue_count: int) -> str:
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


def build_review_content_node(*, context: WorkflowContext):
    """构建内容复核节点。

    章节级 review 按章并行执行，先由 LLM 做结构化复核，再叠加规则兜底；
    所有章节 review fan-in 后再做整本文档一致性检查，并输出
    review_decision 与 ReviewAction 给 repair 阶段使用。
    """

    async def review_content_node(state: DocGenState) -> dict:
        """复核增强后的章节集合并生成回流动作。"""

        started_at = perf_counter()
        enhanced = [
            EnhancedChapterDraft.model_validate(item)
            for item in sorted(
                list(state.get("enhanced_chapter_drafts") or []),
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        if not enhanced:
            return {"error": "没有可复核的增强章节。"}
        # 先把章节相关合同按 chapter_index 对齐，后面逐章复核时就不会靠列表顺序碰运气。
        tasks_by_chapter = {
            int(item.get("chapter_index", 0) or 0): ChapterGenerationTask.model_validate(item)
            for item in list(state.get("chapter_tasks") or [])
        }
        claim_ledgers_by_chapter = {
            int(item.get("chapter_index", 0) or 0): ClaimLedger.model_validate(item)
            for item in list(state.get("claim_ledgers") or [])
        }
        claim_maps_by_chapter = {
            int(item.get("chapter_index", 0) or 0): ClaimEvidenceMap.model_validate(item)
            for item in list(state.get("claim_evidence_maps") or [])
        }
        conflict_reports_by_chapter = {
            int(item.get("chapter_index", 0) or 0): ConflictReport.model_validate(item)
            for item in list(state.get("conflict_reports") or [])
        }
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="reviewing_content",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"正在复核 {len(enhanced)} 个章节的覆盖、证据和一致性。",
        )
        review_parallelism = max(1, min(6, len(enhanced)))
        review_sem = asyncio.Semaphore(review_parallelism)

        async def _review_one(draft: EnhancedChapterDraft):
            async with review_sem:
                return await review_chapter(
                    draft=draft,
                    task=tasks_by_chapter.get(draft.chapter_index),
                    claim_ledger=claim_ledgers_by_chapter.get(draft.chapter_index),
                    claim_evidence_map=claim_maps_by_chapter.get(draft.chapter_index),
                    conflict_report=conflict_reports_by_chapter.get(draft.chapter_index),
                    digest_mode=state.get("digest_mode") or "",
                )

        # 章节复核按章并行；整本文档一致性放在所有章节复核之后统一判断。
        review_results = await asyncio.gather(*(_review_one(draft) for draft in enhanced))
        reviewed = []
        reports = []
        actions = []
        for reviewed_draft, report, chapter_actions in review_results:
            reviewed.append(reviewed_draft)
            reports.append(report)
            actions.extend(chapter_actions)
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
                "review_parallelism": review_parallelism,
                "review_decision": review_decision,
                "review_action_count": len(actions),
                "document_issue_count": len(consistency_report.issues),
            },
        )
        return {
            "reviewed_chapter_drafts": [item.model_dump(mode="json") for item in reviewed],
            "chapter_review_reports": [item.model_dump(mode="json") for item in reports],
            "document_consistency_report": consistency_report.model_dump(mode="json"),
            "review_decision": review_decision,
            "review_actions": [item.model_dump(mode="json") for item in actions],
            "review_ms": elapsed_ms,
            "llm_calls_total": len(enhanced),
        }

    return review_content_node


__all__ = ["build_review_content_node"]
