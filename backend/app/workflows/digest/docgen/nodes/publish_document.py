"""Finalize knowledge docs by staging or publishing them."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt
from app.utils.docgen_store import (
    append_knowledge_build_recent_event,
    update_knowledge_build_merge_preview,
    upsert_knowledge_build_chapter_progress,
)
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import get_effective_chapter_title, publish_docgen_progress
from app.workflows.digest.docgen.lib.publish import (
    publish_staged_knowledge_docs,
    stage_knowledge_docs,
)
from app.workflows.digest.docgen.state import DocGenState

logger = structlog.get_logger()


def build_publish_document_node(*, context: WorkflowContext):
    """构建文档发布节点。

    这是 DocGen 图的最后一步：把章节 metadata、整本 Markdown 和各类
    artifacts 写入 staging、当前发布位置、版本归档和 KnowledgeDoc rows。
    """

    async def publish_document_node(state: DocGenState) -> dict:
        """发布知识文档并写入完整 docgen_manifest。"""

        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="publish_document")
        subject = state["subject"]
        chapter_metadatas = sorted(
            list(state.get("chapter_metadatas", [])),
            key=lambda item: item.get("chapter_index", 0),
        )
        chapter_assignments = list(state.get("chapter_assignments", []))
        document_context = dict(state.get("document_context") or {})
        cover_artifact = dict(state.get("cover_artifact") or {})
        cover_markdown = str(state.get("cover_markdown") or "").strip()
        # 这份快照给后续调试、问答/出题复用和失败追踪用；不要只因为前端暂时不用就删。
        docgen_artifacts = {
            "docgen_context": dict(state.get("docgen_context") or {}),
            "intent_profile": dict(state.get("intent_profile") or {}),
            "file_summaries": list(state.get("file_summaries") or []),
            "source_affinity_by_chapter": list(state.get("source_affinity_by_chapter") or []),
            "high_confidence_evidence_units": list(state.get("high_confidence_evidence_units") or []),
            "chapter_generation_plan_seed": dict(state.get("chapter_generation_plan_seed") or {}),
            "chapter_task_seeds": list(state.get("chapter_task_seeds") or []),
            "backbone_research_agenda": dict(state.get("backbone_research_agenda") or {}),
            "document_backbone_snapshot": dict(state.get("document_backbone") or {}),
            "backbone_conflict_warnings": list(state.get("backbone_conflict_warnings") or []),
            "chapter_generation_plan": dict(state.get("chapter_generation_plan") or {}),
            "chapter_drafts": list(state.get("chapter_drafts") or []),
            "enhanced_chapter_drafts": list(state.get("enhanced_chapter_drafts") or []),
            "reviewed_chapter_drafts": list(state.get("reviewed_chapter_drafts") or []),
            "research_traces": list(state.get("research_traces") or []),
            "evidence_ledgers": list(state.get("evidence_ledgers") or []),
            "claim_ledgers": list(state.get("claim_ledgers") or []),
            "claim_evidence_maps": list(state.get("claim_evidence_maps") or []),
            "conflict_reports": list(state.get("conflict_reports") or []),
            "chapter_review_reports": list(state.get("chapter_review_reports") or []),
            "document_consistency_report": dict(state.get("document_consistency_report") or {}),
            "review_decision": str(state.get("review_decision") or ""),
            "review_actions": list(state.get("review_actions") or []),
            "unresolved_warnings": list(state.get("unresolved_warnings") or []),
            "repair_loop_state": dict(state.get("repair_loop_state") or {}),
            "repair_trace": list(state.get("repair_trace") or []),
            "source_trust_summary": dict((state.get("document_backbone") or {}).get("source_trust_summary") or {}),
            "asset_manifest": {
                "assets": [
                    asset
                    for manifest in list(state.get("asset_manifests") or [])
                    for asset in list((manifest or {}).get("assets") or [])
                ]
            },
            "practice_manifest": {
                "questions": [
                    question
                    for manifest in list(state.get("practice_manifests") or [])
                    for question in list((manifest or {}).get("questions") or [])
                ]
            },
            "merge_review_report": dict(state.get("merge_review_report") or {}),
            "final_chapter_titles": list(state.get("final_chapter_titles") or []),
            "title_review_report": dict(state.get("title_review_report") or {}),
            "cover_artifact": cover_artifact,
        }
        user_prompt = state.get("user_prompt")
        requested_at = state["requested_at"]
        standalone = True

        if not chapter_metadatas:
            return {"error": "当前没有可用于最终发布的章节内容。"}

        node_logger.info(
            "docgen_finalize_started",
            chapter_count=len(chapter_metadatas),
            requested_at=requested_at.isoformat(),
            standalone=standalone,
        )

        staged_docs = await stage_knowledge_docs(
            subject=subject,
            chapter_metadatas=chapter_metadatas,
            document_context=document_context,
            cover_markdown=cover_markdown,
            docgen_artifacts=docgen_artifacts,
        )

        doc_ids: list[int] = []
        if standalone:
            doc_ids = publish_staged_knowledge_docs(
                subject=subject,
                chapter_metadatas=chapter_metadatas,
                chapter_assignments=chapter_assignments,
                document_context=document_context,
                cover_markdown=cover_markdown,
                user_prompt=user_prompt,
                requested_at=requested_at,
                version_no=1,
                build_session_id=state.get("build_session_id"),
                docgen_artifacts=docgen_artifacts,
            )
            node_logger.info("docgen_standalone_publish_completed", doc_count=len(doc_ids))

        update_knowledge_build_merge_preview(
            subject,
            requested_at=requested_at,
            merge_preview={
                "latest_chapter_titles": [str(chapter.get("title") or "").strip() for chapter in chapter_metadatas],
                "draft_excerpt": build_draft_excerpt(staged_docs.merged_markdown, max_chars=1600),
            },
        )

        for chapter in chapter_metadatas:
            title = get_effective_chapter_title(
                chapter,
                fallback_index=int(chapter.get("chapter_index", 0) or 0) or None,
            )
            if title == "练习与自检":
                continue
            upsert_knowledge_build_chapter_progress(
                subject,
                requested_at=requested_at,
                chapter_progress={
                    "chapter_index": int(chapter.get("chapter_index", 0) or 0),
                    "title": title,
                    "status": "completed",
                    "source_count": len(list(chapter.get("sources") or [])),
                    "local_hits": int(chapter.get("local_hits", 0) or 0),
                    "web_hits": int(chapter.get("web_hits", 0) or 0),
                    "query_count": int(chapter.get("query_count", 0) or 0),
                    "word_count": int(chapter.get("word_count", 0) or 0),
                    "fallback_used": bool(chapter.get("fallback_used", False)),
                },
            )

        finalize_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_finalize_completed",
            chapter_count=len(staged_docs.built_paths),
            merged_chars=len(staged_docs.merged_markdown),
            finalize_ms=finalize_ms,
            published=standalone,
        )
        append_knowledge_build_recent_event(
            subject,
            requested_at=requested_at,
            event={
                "stage": "docgen_finalized",
                "summary": (
                    f"知识文档已发布，共 {len(doc_ids)} 篇正式文档。"
                    if standalone
                    else f"知识文档草稿已暂存，共 {len(staged_docs.built_paths)} 个章节。"
                ),
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_finalized",
            payload={
                "chapter_count": len(staged_docs.built_paths),
                "published_doc_count": len(doc_ids),
                "draft_available": bool(staged_docs.merged_markdown.strip()),
            },
        )
        return {
            "doc_ids": doc_ids,
            "built_paths": staged_docs.built_paths,
            "merged_markdown": staged_docs.merged_markdown,
            "user_prompt": user_prompt,
            "finalize_ms": finalize_ms,
        }

    return publish_document_node


__all__ = ["build_publish_document_node"]
