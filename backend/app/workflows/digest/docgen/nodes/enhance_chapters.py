"""Enhance one generated DocGen chapter."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    update_knowledge_build_status,
    upsert_knowledge_build_chapter_preview,
    upsert_knowledge_build_chapter_progress,
)
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.chapter_enhancement import enhance_chapter_draft
from app.workflows.digest.docgen.lib.models import ChapterDraft, ClaimLedger
from app.workflows.digest.docgen.nodes.common import extract_markdown_preview_headings, publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.prefetch import start_docgen_kg_prefetch_incremental


def build_enhance_chapters_node(*, context: WorkflowContext):
    """构建章节增强节点。

    该节点在所有章节草稿 fan-in 后运行，但内部会并行增强每章。增强只
    处理表现层：资产占位、公式和 Markdown 结构，不负责生成标题、
    练习或其它语义内容。
    """

    async def enhance_chapters_node(state: DocGenState) -> dict:
        """并行增强章节草稿并产出资产 manifest。"""

        started_at = perf_counter()
        draft_items = list(state.get("unit_test_chapter_drafts") or state.get("chapter_drafts") or [])
        drafts = [
            ChapterDraft.model_validate(item)
            for item in sorted(
                draft_items,
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        if not drafts:
            return {"error": "没有可增强的章节草稿。"}
        claim_ledgers_by_chapter = {
            int(item.get("chapter_index", 0) or 0): ClaimLedger.model_validate(item)
            for item in list(state.get("claim_ledgers") or [])
        }
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="enhancing_chapters",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"章节初稿已生成，正在并行增强 {len(drafts)} 个章节。",
        )
        used_static_figure_signatures: set[str] = set()

        async def _enhance_one(draft: ChapterDraft):
            traced_context = TracedExecutionContext(
                course_id=state["course_id"],
                build_session_id=state.get("build_session_id", ""),
                workflow_context=context,
                planner_session_id=state.get("planner_session_id", ""),
                confirmed_plan_id=state.get("confirmed_plan_id", ""),
                digest_mode=state.get("digest_mode", ""),
                teaching_action="chapter_enhance",
                chapter_index=draft.chapter_index,
            )
            upsert_knowledge_build_chapter_progress(
                state["course_id"],
                requested_at=state["requested_at"],
                chapter_progress={"chapter_index": draft.chapter_index, "title": draft.title, "status": "enhancing"},
            )
            upsert_knowledge_build_chapter_preview(
                state["course_id"],
                requested_at=state["requested_at"],
                chapter_preview={
                    "chapter_index": draft.chapter_index,
                    "title": draft.title,
                    "status": "enhancing",
                },
            )
            enhanced, asset_manifest, practice_manifest = await enhance_chapter_draft(
                draft,
                traced_context=traced_context,
                digest_mode=state.get("digest_mode") or "systematic",
                claim_ledger=claim_ledgers_by_chapter.get(draft.chapter_index),
                used_static_figure_signatures=used_static_figure_signatures,
            )
            word_count = count_words(enhanced.markdown)
            upsert_knowledge_build_chapter_preview(
                state["course_id"],
                requested_at=state["requested_at"],
                chapter_preview={
                    "chapter_index": draft.chapter_index,
                    "title": enhanced.title,
                    "status": "enhanced",
                    "excerpt": enhanced.markdown.strip(),
                    "latest_headings": extract_markdown_preview_headings(enhanced.markdown),
                    "word_count": word_count,
                    "source_count": len(enhanced.source_details),
                },
            )
            upsert_knowledge_build_chapter_progress(
                state["course_id"],
                requested_at=state["requested_at"],
                chapter_progress={
                    "chapter_index": draft.chapter_index,
                    "title": enhanced.title,
                    "status": "enhanced",
                    "source_count": len(enhanced.source_details),
                    "word_count": word_count,
                },
            )
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                event={
                    "stage": "chapter_enhanced",
                    "chapter_index": draft.chapter_index,
                    "title": enhanced.title,
                    "summary": f"{enhanced.title} 章节展示增强完成，资产 {len(asset_manifest.assets)} 个。",
                    "created_at": utcnow(),
                },
            )
            return enhanced, asset_manifest, practice_manifest

        results = await run_llm_tasks(
            drafts,
            _enhance_one,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        enhanced_items = [item[0] for item in results]
        asset_manifests = [item[1] for item in results]
        practice_manifests = [item[2] for item in results]
        kg_prefetch_incremental_started = start_docgen_kg_prefetch_incremental(
            course_id=state["course_id"],
            build_session_id=state.get("build_session_id", ""),
            chapters=[item.model_dump(mode="json") for item in enhanced_items],
            document_backbone=state.get("document_backbone") or {},
            docgen_manifest={
                "intent_profile": dict(state.get("intent_profile") or state.get("intent_core") or {}),
                "chapter_task_seeds": list(state.get("chapter_task_seeds") or []),
                "chapter_execution_briefs": list(state.get("chapter_execution_briefs") or []),
                "chapter_generation_plan": dict(state.get("chapter_generation_plan") or {}),
                "chapter_generation_plan_seed": dict(state.get("chapter_generation_plan_seed") or {}),
                "document_backbone_snapshot": dict(state.get("document_backbone") or {}),
                "preliminary_kg": dict(state.get("preliminary_kg") or {}),
                "kg_refinement_items": list(state.get("kg_refinement_items") or []),
                "docgen_kg_draft": dict(state.get("docgen_kg_draft") or {}),
                "digest_mode": str(state.get("digest_mode") or ""),
                "kg_prefetch_phase": "enhanced_chapters_incremental",
            },
        )
        kg_prefetch_status = (
            "incremental_from_enhanced_chapters"
            if kg_prefetch_incremental_started
            else "not_started_from_enhanced_chapters"
        )
        if kg_prefetch_incremental_started:
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                event={
                    "stage": "kg_prefetch_incremental_started",
                    "summary": "增强后的章节已追加进入知识图谱预抽取，不打断已有图谱 sidecar。",
                    "created_at": utcnow(),
                },
            )
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="chapters_enhanced",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"章节增强完成，共生成 {len(enhanced_items)} 个章节草稿。",
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapters_enhanced",
            payload={
                "chapter_count": len(enhanced_items),
                "asset_count": sum(len(item.assets) for item in asset_manifests),
                "practice_count": sum(len(item.questions) for item in practice_manifests),
                "warning_count": sum(len(item.warnings) for item in enhanced_items),
                "kg_prefetch_started": kg_prefetch_incremental_started,
                "kg_prefetch_incremental_started": kg_prefetch_incremental_started,
                "kg_prefetch_status": kg_prefetch_status,
            },
        )
        return {
            "enhanced_chapter_drafts": [item.model_dump(mode="json") for item in enhanced_items],
            "asset_manifests": [item.model_dump(mode="json") for item in asset_manifests],
            "practice_manifests": [item.model_dump(mode="json") for item in practice_manifests],
            "kg_prefetch_status": kg_prefetch_status,
            "enhance_ms": elapsed_ms,
        }

    return enhance_chapters_node


__all__ = ["build_enhance_chapters_node"]
