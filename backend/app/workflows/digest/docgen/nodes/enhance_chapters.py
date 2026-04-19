"""Enhance one generated DocGen chapter."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.shared.infra.execution import TracedExecutionContext
from app.utils.docgen_store import (
    append_knowledge_build_recent_event,
    update_knowledge_build_status,
    upsert_knowledge_build_chapter_progress,
)
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.chapter_enhancement import enhance_chapter_draft
from app.workflows.digest.docgen.lib.models import ChapterDraft, ClaimLedger, DocumentBackbone
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress, resolve_docgen_course_type
from app.workflows.digest.docgen.state import DocGenState


def build_enhance_chapters_node(*, context: WorkflowContext):
    """构建章节增强节点。

    该节点在所有章节草稿 fan-in 后运行，但内部会并行增强每章。增强只
    处理表现层：资产占位、公式、Markdown 结构和自检题，不负责修核心知识。
    """

    async def enhance_chapters_node(state: DocGenState) -> dict:
        """并行增强章节草稿并产出资产/练习 manifest。"""

        started_at = perf_counter()
        drafts = [
            ChapterDraft.model_validate(item)
            for item in sorted(
                list(state.get("chapter_drafts") or []),
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        if not drafts:
            return {"error": "没有可增强的章节草稿。"}
        claim_ledgers_by_chapter = {
            int(item.get("chapter_index", 0) or 0): ClaimLedger.model_validate(item)
            for item in list(state.get("claim_ledgers") or [])
        }
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="enhancing_chapters",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description=f"章节初稿已生成，正在并行增强 {len(drafts)} 个章节。",
        )

        async def _enhance_one(draft: ChapterDraft):
            traced_context = TracedExecutionContext(
                subject=state["subject"],
                build_session_id=state.get("build_session_id", ""),
                workflow_context=context,
                planner_session_id=state.get("planner_session_id", ""),
                confirmed_plan_id=state.get("confirmed_plan_id", ""),
                digest_mode=state.get("digest_mode", ""),
                course_type=resolve_docgen_course_type(state.get("course_type") or state.get("digest_mode")),
                teaching_action="chapter_enhance",
                chapter_index=draft.chapter_index,
            )
            upsert_knowledge_build_chapter_progress(
                state["subject"],
                requested_at=state["requested_at"],
                chapter_progress={"chapter_index": draft.chapter_index, "title": draft.title, "status": "enhancing"},
            )
            enhanced, asset_manifest, practice_manifest = await enhance_chapter_draft(
                draft,
                traced_context=traced_context,
                digest_mode=state.get("digest_mode") or "systematic",
                claim_ledger=claim_ledgers_by_chapter.get(draft.chapter_index),
                document_backbone=document_backbone,
            )
            upsert_knowledge_build_chapter_progress(
                state["subject"],
                requested_at=state["requested_at"],
                chapter_progress={
                    "chapter_index": draft.chapter_index,
                    "title": enhanced.title,
                    "status": "enhanced",
                    "source_count": len(enhanced.source_details),
                },
            )
            append_knowledge_build_recent_event(
                state["subject"],
                requested_at=state["requested_at"],
                event={
                    "stage": "chapter_enhanced",
                    "chapter_index": draft.chapter_index,
                    "title": enhanced.title,
                    "summary": f"{enhanced.title} 章节增强完成，资产 {len(asset_manifest.assets)} 个，自检题 {len(practice_manifest.questions)} 个。",
                    "created_at": utcnow(),
                },
            )
            return enhanced, asset_manifest, practice_manifest

        results = await asyncio.gather(*(_enhance_one(draft) for draft in drafts))
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        enhanced_items = [item[0] for item in results]
        asset_manifests = [item[1] for item in results]
        practice_manifests = [item[2] for item in results]
        update_knowledge_build_status(
            state["subject"],
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
            },
        )
        return {
            "enhanced_chapter_drafts": [item.model_dump(mode="json") for item in enhanced_items],
            "asset_manifests": [item.model_dump(mode="json") for item in asset_manifests],
            "practice_manifests": [item.model_dump(mode="json") for item in practice_manifests],
            "enhance_ms": elapsed_ms,
        }

    return enhance_chapters_node


__all__ = ["build_enhance_chapters_node"]
