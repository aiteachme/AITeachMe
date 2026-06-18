"""Review enhanced DocGen content before merge."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.llm_support import get_llm_concurrency_limit
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
from app.workflows.digest.docgen.lib.pipeline_context import (
    contract_item_for_chapter,
    evidence_items_for_chapter,
    guideline_summary_for_chapter,
    learner_profile_text_for_branch,
)
from app.workflows.digest.docgen.lib.pipeline_artifacts import build_chapter_kg_refinement_item
from app.workflows.digest.docgen.nodes.common import extract_markdown_preview_headings, publish_docgen_progress
from app.workflows.digest.docgen.lib.quality import review_document_consistency, review_document_consistency_with_llm
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.prefetch import (
    start_docgen_kg_prefetch,
    start_docgen_kg_prefetch_incremental,
)


def _review_decision(actions: list[ReviewAction], *, document_issue_count: int, document_has_error: bool = False) -> str:
    blocking_types = {"section_patch", "evidence_patch", "regenerate_chapter", "re_dispatch", "rebuild_backbone"}
    has_blocking_action = any(
        action.action_type in blocking_types and action.severity in {"warning", "error"}
        for action in actions
    )
    has_error_action = any(action.severity == "error" for action in actions)
    if has_error_action or document_has_error:
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


def _single_or_by_chapter(
    state: DocGenState,
    *,
    model_cls,
    chapter_index: int,
    single_key: str,
    collection_key: str,
):
    single = state.get(single_key)
    if isinstance(single, dict) and single:
        try:
            parsed = model_cls.model_validate(single)
            if int(getattr(parsed, "chapter_index", 0) or 0) == chapter_index:
                return parsed
        except Exception:
            pass
    return _by_chapter(model_cls, list(state.get(collection_key) or [])).get(chapter_index)


def _materialize_reviewed_chapters(state: DocGenState) -> list[ReviewedChapterDraft]:
    overlays_by_chapter = {
        int(item.get("chapter_index", 0) or 0): item
        for item in list(state.get("reviewed_chapter_overlay_items") or [])
        if isinstance(item, dict)
    }
    enhanced_items = sorted(
        list(state.get("enhanced_chapter_drafts") or []),
        key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
    )
    if enhanced_items:
        reviewed: list[ReviewedChapterDraft] = []
        for item in enhanced_items:
            draft = EnhancedChapterDraft.model_validate(item)
            overlay = overlays_by_chapter.get(draft.chapter_index, {})
            reviewed.append(
                ReviewedChapterDraft.model_validate(
                    {
                        **draft.model_dump(mode="json"),
                        "review_report_ref": str(overlay.get("review_report_ref") or ""),
                        "warnings": list(overlay.get("warnings") or draft.warnings),
                        "patched": bool(overlay.get("patched", False)),
                    }
                )
            )
        return reviewed
    return [
        ReviewedChapterDraft.model_validate(item)
        for item in sorted(
            list(state.get("reviewed_chapter_draft_items") or []),
            key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
        )
    ]


def _review_kg_manifest(
    state: DocGenState,
    *,
    phase: str,
    kg_refinement_items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    refinement_items = [
        *list(state.get("kg_refinement_items") or []),
        *list(kg_refinement_items or []),
    ]
    return {
        "intent_profile": dict(state.get("intent_profile") or state.get("intent_core") or {}),
        "intent_enhanced": dict(state.get("intent_enhanced") or {}),
        "summary_enhanced": dict(state.get("summary_enhanced") or {}),
        "user_profile": dict(state.get("user_profile") or {}),
        "chapters_enhanced": list(state.get("chapters_enhanced") or []),
        "chapter_task_seeds": list(state.get("chapter_task_seeds") or []),
        "chapter_execution_briefs": list(state.get("chapter_execution_briefs") or []),
        "chapter_generation_plan": dict(state.get("chapter_generation_plan") or {}),
        "chapter_generation_plan_seed": dict(state.get("chapter_generation_plan_seed") or {}),
        "document_backbone_snapshot": dict(state.get("document_backbone") or {}),
        "guideline": dict(state.get("guideline") or {}),
        "dispatch_table": dict(state.get("dispatch_table") or {}),
        "preliminary_kg": dict(state.get("preliminary_kg") or {}),
        "kg_refinement_items": refinement_items,
        "docgen_kg_draft": dict(state.get("docgen_kg_draft") or {}),
        "review_actions": list(state.get("review_action_items") or state.get("review_actions") or []),
        "digest_mode": str(state.get("digest_mode") or ""),
        "kg_prefetch_phase": phase,
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
        task = _single_or_by_chapter(
            state,
            model_cls=ChapterGenerationTask,
            chapter_index=draft.chapter_index,
            single_key="review_chapter_task",
            collection_key="chapter_tasks",
        )
        claim_ledger = _single_or_by_chapter(
            state,
            model_cls=ClaimLedger,
            chapter_index=draft.chapter_index,
            single_key="review_claim_ledger",
            collection_key="claim_ledgers",
        )
        claim_evidence_map = _single_or_by_chapter(
            state,
            model_cls=ClaimEvidenceMap,
            chapter_index=draft.chapter_index,
            single_key="review_claim_evidence_map",
            collection_key="claim_evidence_maps",
        )
        conflict_report = _single_or_by_chapter(
            state,
            model_cls=ConflictReport,
            chapter_index=draft.chapter_index,
            single_key="review_conflict_report",
            collection_key="conflict_reports",
        )
        user_profile = dict(state.get("user_profile") or {})
        dispatch_item = contract_item_for_chapter(dict(state.get("dispatch_table") or {}), draft.chapter_index)
        chapter_contract = contract_item_for_chapter(
            {"items": state.get("chapters_enhanced") or []},
            draft.chapter_index,
        )
        guideline_summary = guideline_summary_for_chapter(dict(state.get("guideline") or {}), draft.chapter_index)
        evidence_items = evidence_items_for_chapter(dict(state.get("summary_enhanced") or {}), draft.chapter_index)
        learner_profile_text = learner_profile_text_for_branch(
            state_profile_text=state.get("learner_profile_text", ""),
            user_profile=user_profile,
        )

        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="reviewing_content",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在并行复核章节覆盖、证据支撑和写作质量。",
        )
        upsert_knowledge_build_chapter_progress(
            state["course_id"],
            requested_at=state["requested_at"],
            chapter_progress={"chapter_index": draft.chapter_index, "title": draft.title, "status": "reviewing"},
        )
        upsert_knowledge_build_chapter_preview(
            state["course_id"],
            requested_at=state["requested_at"],
            chapter_preview={
                "chapter_index": draft.chapter_index,
                "title": draft.title,
                "status": "reviewing",
            },
        )
        reviewed, report, actions = await review_chapter(
            draft=draft,
            task=task,
            claim_ledger=claim_ledger,
            claim_evidence_map=claim_evidence_map,
            conflict_report=conflict_report,
            digest_mode=state.get("digest_mode") or "",
            guideline_summary=guideline_summary,
            dispatch_item=dispatch_item,
            chapter_contract=chapter_contract,
            evidence_items=evidence_items,
            learner_profile_text=learner_profile_text,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        upsert_knowledge_build_chapter_progress(
            state["course_id"],
            requested_at=state["requested_at"],
            chapter_progress={"chapter_index": draft.chapter_index, "title": draft.title, "status": "reviewed"},
        )
        upsert_knowledge_build_chapter_preview(
            state["course_id"],
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
            state["course_id"],
            requested_at=state["requested_at"],
            event={
                "stage": "chapter_reviewed",
                "chapter_index": draft.chapter_index,
                "title": reviewed.title,
                "summary": f"{reviewed.title} 内容复核完成，发现 {len(actions)} 条回流建议。",
                "created_at": utcnow(),
            },
        )
        kg_refinement_item = build_chapter_kg_refinement_item(
            reviewed=reviewed,
            report=report,
            actions=actions,
        )
        kg_prefetch_incremental_started = start_docgen_kg_prefetch_incremental(
            course_id=state["course_id"],
            build_session_id=state.get("build_session_id", ""),
            chapters=[reviewed.model_dump(mode="json")],
            document_backbone=dict(state.get("document_backbone") or {}),
            docgen_manifest=_review_kg_manifest(
                state,
                phase="reviewed_chapter_incremental",
                kg_refinement_items=[kg_refinement_item],
            ),
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
                "kg_refinement_node_count": int(kg_refinement_item.get("node_count", 0) or 0),
                "kg_refinement_edge_count": int(kg_refinement_item.get("edge_count", 0) or 0),
                "kg_prefetch_incremental_started": kg_prefetch_incremental_started,
            },
        )
        return {
            "reviewed_chapter_overlay_items": [
                {
                    "chapter_index": reviewed.chapter_index,
                    "review_report_ref": reviewed.review_report_ref,
                    "warnings": reviewed.warnings,
                    "patched": reviewed.patched,
                }
            ],
            "chapter_review_report_items": [report.model_dump(mode="json")],
            "review_action_items": [item.model_dump(mode="json") for item in actions],
            "kg_refinement_items": [kg_refinement_item],
            "review_ms": elapsed_ms,
            "llm_calls_total": 1,
        }

    return review_chapter_node


def build_document_consistency_review_node(*, context: WorkflowContext):
    """构建整本一致性复核节点。

    所有章节复核 fan-in 后运行，先做规则基线，再做一次整本文档结构化
    LLM 复核，只输出跨章问题和回流动作，不直接重写正文。
    """

    async def document_consistency_review_node(state: DocGenState) -> dict:
        """汇总章节 review 并生成 review_decision。"""

        started_at = perf_counter()
        reviewed = _materialize_reviewed_chapters(state)
        if not reviewed:
            return {"error": "没有可做整本一致性复核的章节。"}
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        actions = [
            ReviewAction.model_validate(item)
            for item in list(state.get("review_action_items") or [])
        ]
        kg_prefetch_started = start_docgen_kg_prefetch(
            course_id=state["course_id"],
            build_session_id=state.get("build_session_id", ""),
            chapters=[item.model_dump(mode="json") for item in reviewed],
            document_backbone=dict(state.get("document_backbone") or {}),
            docgen_manifest=_review_kg_manifest(state, phase="reviewed_markdown"),
        )
        kg_prefetch_status = (
            "refreshed_from_reviewed_chapters" if kg_prefetch_started else "not_started_from_reviewed_chapters"
        )
        if len(reviewed) <= 1:
            consistency_report = review_document_consistency(
                reviewed_chapters=reviewed,
                document_backbone=document_backbone,
                expected_chapter_count=len(list(state.get("chapter_tasks") or [])),
            )
            consistency_report = consistency_report.model_copy(
                update={
                    "source_summary": {
                        **dict(consistency_report.source_summary or {}),
                        "document_review_mode": "single_chapter_rule_guardrail",
                    }
                }
            )
            document_actions = []
            llm_calls = 0
        else:
            consistency_report, document_actions, llm_calls = await review_document_consistency_with_llm(
                reviewed_chapters=reviewed,
                document_backbone=document_backbone,
                expected_chapter_count=len(list(state.get("chapter_tasks") or [])),
                digest_mode=state.get("digest_mode") or "",
                guideline=dict(state.get("guideline") or {}),
                dispatch_table=dict(state.get("dispatch_table") or {}),
                learner_profile_text=str(state.get("learner_profile_text") or ""),
            )
        actions = [*actions, *document_actions]
        review_decision = _review_decision(
            actions,
            document_issue_count=len(consistency_report.issues),
            document_has_error=any(
                str(item.get("severity") or "") == "error"
                for item in list(consistency_report.issues or [])
                if isinstance(item, dict)
            ),
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="content_reviewed",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"内容复核完成，决策 {review_decision}，记录 {len(actions)} 条回流建议。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
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
                "review_parallelism": min(get_llm_concurrency_limit(), len(reviewed)),
                "review_decision": review_decision,
                "review_action_count": len(actions),
                "document_issue_count": len(consistency_report.issues),
                "document_review_llm_calls": llm_calls,
                "kg_prefetch_status": kg_prefetch_status,
            },
        )
        return {
            "reviewed_chapter_drafts": [item.model_dump(mode="json") for item in reviewed],
            "chapter_review_reports": list(state.get("chapter_review_report_items") or []),
            "review_actions": [item.model_dump(mode="json") for item in actions],
            "document_consistency_report": consistency_report.model_dump(mode="json"),
            "review_decision": review_decision,
            "kg_prefetch_status": kg_prefetch_status,
            "review_ms": elapsed_ms,
            "llm_calls_total": llm_calls,
        }

    return document_consistency_review_node


__all__ = ["build_document_consistency_review_node", "build_review_chapter_node"]
