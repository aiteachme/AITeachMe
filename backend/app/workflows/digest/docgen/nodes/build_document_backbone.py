"""Build the document-level knowledge backbone."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.shared.infra.settings import get_settings
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.document_backbone import (
    generate_document_backbone,
)
from app.workflows.digest.docgen.lib.models import (
    BackboneResearchAgenda,
    ChapterGenerationPlanSeed,
    ChapterGenerationTaskSeed,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
)
from app.workflows.digest.docgen.lib.pipeline_artifacts import (
    build_chapters_enhanced,
    build_dispatch_table,
    build_guideline,
    build_preliminary_kg,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


_BACKBONE_PROGRESS_INTERVAL_S = 4.0


def _node_type_counts(preliminary_kg: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in list(preliminary_kg.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node_type = str(item.get("knowledge_unit_type") or "concept").strip() or "concept"
        counts[node_type] = counts.get(node_type, 0) + 1
    return counts


def _sample_nodes(preliminary_kg: dict[str, object]) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for item in list(preliminary_kg.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        samples.append(
            {
                "name": name[:80],
                "type": str(item.get("knowledge_unit_type") or "concept").strip() or "concept",
                "summary": str(item.get("summary") or "").strip()[:160],
            }
        )
        if len(samples) >= 8:
            break
    return samples


_BACKBONE_SECTION_LABELS = {
    "canonical_glossary": "统一术语",
    "concept_dependency_graph": "跨章依赖",
    "notation_registry": "符号约定",
    "canonical_claim_pool": "核心主张",
    "confusion_map": "易混点",
}


def _compact_preview_items(items: object, *, limit: int = 4) -> str:
    if not isinstance(items, list):
        return ""
    visible = [
        str(item or "").strip().rstrip("。；;")
        for item in items
        if str(item or "").strip().rstrip("。；;")
    ][:limit]
    return "；".join(visible)


def build_document_backbone_node(*, context: WorkflowContext):
    """构建文档级知识骨架节点。

    读取章节 seed、资料摘要和高置信证据候选，生成整本文档的术语、
    主张、概念依赖和易混点，再把这些全局约束回填到每章任务。
    """

    async def document_backbone_node(state: DocGenState) -> dict:
        """生成 DocumentBackbone。"""

        started_at = perf_counter()
        task_seeds = [
            ChapterGenerationTaskSeed.model_validate(item)
            for item in list(state.get("chapter_task_seeds") or [])
        ]
        if not task_seeds:
            return {"error": "DocGen 知识骨架构建失败：缺少章节 seed。"}
        agenda = BackboneResearchAgenda.model_validate(state.get("backbone_research_agenda") or {})
        evidence_units = [
            HighConfidenceEvidenceUnit.model_validate(item)
            for item in list(state.get("high_confidence_evidence_units") or [])
        ]
        file_summaries = [
            FileMaterialSummary.model_validate(item)
            for item in list(state.get("file_summaries") or [])
        ]
        plan_seed = ChapterGenerationPlanSeed.model_validate(state.get("chapter_generation_plan_seed") or {})
        title_by_chapter = {
            int(seed.chapter_index): seed.enhanced_title or seed.confirmed_title
            for seed in task_seeds
        }
        wait_intervals_since_visible_progress = 0

        async def publish_preparation_preview(kind: str, payload: dict[str, object]) -> None:
            nonlocal wait_intervals_since_visible_progress
            wait_intervals_since_visible_progress = 0
            chapter_index: int | None = None
            title: str | None = None
            if kind == "backbone_section":
                section = str(payload.get("section") or "")
                label = _BACKBONE_SECTION_LABELS.get(section, "骨架内容")
                item_count = int(payload.get("item_count", 0) or 0)
                item_preview = _compact_preview_items(payload.get("items"))
                summary = f"{label}已生成 {item_count} 项"
                if item_preview:
                    summary = f"{summary}：{item_preview}。"
                else:
                    summary = f"{summary}，本轮无需额外约束。"
                stage = "document_backbone_section"
            elif kind == "chapter_execution_brief":
                chapter_index = int(payload.get("chapter_index", 0) or 0)
                title = title_by_chapter.get(chapter_index) or f"第 {chapter_index} 章"
                outline = _compact_preview_items(payload.get("teaching_outline"), limit=4)
                instructions = _compact_preview_items(payload.get("writing_instructions"), limit=2)
                queries = _compact_preview_items(payload.get("retrieval_queries"), limit=2)
                parts = [f"讲解路径：{outline}" if outline else ""]
                if instructions:
                    parts.append(f"写作重点：{instructions}")
                if queries:
                    parts.append(f"检索：{queries}")
                summary = f"第 {chapter_index} 章《{title}》执行 brief 已生成：" + "；".join(
                    part for part in parts if part
                )
                summary = summary.rstrip("：") + "。"
                stage = "chapter_execution_brief_ready"
            else:
                summary = "流式骨架草案未通过最终结构校验，正在自动修复并重新校验。"
                stage = "document_backbone_repairing"

            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                build_group_id=state.get("build_group_id") or None,
                event={
                    "stage": stage,
                    "chapter_index": chapter_index,
                    "title": title,
                    "summary": summary,
                    "created_at": utcnow(),
                },
            )
            await publish_docgen_progress(
                context,
                state=state,
                stage=stage,
                payload={**payload},
            )

        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            status="running",
            stage="building_document_backbone",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在统一术语、主张、证据和易混点，构建整本文档知识骨架。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={
                "stage": "building_document_backbone",
                "summary": (
                    f"已将 {len(task_seeds)} 个章节合同、{len(file_summaries)} 份资料摘要和 "
                    f"{len(evidence_units)} 个证据单元送入模型，正在统一整本知识骨架。"
                ),
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="building_document_backbone",
            payload={
                "chapter_count": len(task_seeds),
                "evidence_unit_count": len(evidence_units),
                "file_summary_count": len(file_summaries),
            },
        )
        generation_task = asyncio.create_task(
            generate_document_backbone(
                course_name=plan_seed.course_name or str(state.get("course_name") or ""),
                digest_mode=str(state.get("digest_mode") or plan_seed.digest_mode or "systematic"),
                task_seeds=task_seeds,
                agenda=agenda,
                evidence_units=evidence_units,
                file_summaries=file_summaries,
                learner_profile_text=str(state.get("learner_profile_text") or ""),
                max_retrieval_queries_per_chapter=(
                    get_settings().docgen.max_retrieval_queries_per_chapter
                ),
                extra_metadata={
                    "build_session_id": state.get("build_session_id") or "",
                    "planner_session_id": state.get("planner_session_id") or "",
                    "confirmed_plan_id": state.get("confirmed_plan_id") or "",
                },
                progress_callback=publish_preparation_preview,
            ),
            name=f"docgen.document_backbone:{state['course_id']}",
        )
        try:
            while True:
                try:
                    document_backbone, chapter_briefs, warnings = await asyncio.wait_for(
                        asyncio.shield(generation_task),
                        timeout=_BACKBONE_PROGRESS_INTERVAL_S,
                    )
                    break
                except TimeoutError:
                    wait_intervals_since_visible_progress += 1
                    if wait_intervals_since_visible_progress < 2:
                        continue
                    wait_intervals_since_visible_progress = 0
                    elapsed_s = max(1, int(perf_counter() - started_at))
                    summary = (
                        f"骨架模型仍在处理 {len(task_seeds)} 个章节：正在统一术语、核心主张和章节执行 brief，"
                        f"已持续 {elapsed_s} 秒。"
                    )
                    append_knowledge_build_recent_event(
                        state["course_id"],
                        requested_at=state["requested_at"],
                        build_group_id=state.get("build_group_id") or None,
                        event={
                            "stage": "document_backbone_progress",
                            "summary": summary,
                            "created_at": utcnow(),
                        },
                    )
                    await publish_docgen_progress(
                        context,
                        state=state,
                        stage="document_backbone_progress",
                        payload={
                            "chapter_count": len(task_seeds),
                            "elapsed_seconds": elapsed_s,
                        },
                    )
        finally:
            if not generation_task.done():
                generation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await generation_task

        guideline = build_guideline(
            document_backbone=document_backbone,
            writing_rules=plan_seed.writing_rules,
        )
        chapters_enhanced = build_chapters_enhanced(
            task_seeds=task_seeds,
            summary_enhanced=dict(state.get("summary_enhanced") or {}),
        )
        dispatch_table = build_dispatch_table(
            chapter_tasks=task_seeds,
            guideline=guideline,
            summary_enhanced=dict(state.get("summary_enhanced") or {}),
        )
        preliminary_kg = build_preliminary_kg(
            chapters_enhanced=chapters_enhanced,
            dispatch_table=dispatch_table,
            guideline=guideline,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            status="running",
            stage="preparing_chapter_execution_briefs",
            digest_mode=state.get("digest_mode") or None,
            total_chunks=len(task_seeds),
            processed_chunks=0,
            current_chunk=0,
            discovered_node_count=int(preliminary_kg.get("node_count", 0) or 0),
            discovered_node_types=_node_type_counts(preliminary_kg),
            sample_nodes=_sample_nodes(preliminary_kg),
            metrics={
                "docgen_preliminary_kg_node_count": int(preliminary_kg.get("node_count", 0) or 0),
                "docgen_preliminary_kg_edge_count": int(preliminary_kg.get("edge_count", 0) or 0),
                "docgen_preliminary_kg_stage": "document_backbone_ready",
            },
            current_stage_description=f"整本知识骨架和 {len(chapter_briefs)} 个章节执行 brief 已生成，正在装配章节任务。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={
                "stage": "document_backbone_ready",
                "summary": (
                    f"整本文档准备已完成：术语 {len(document_backbone.canonical_glossary)} 个，"
                    f"主张 {len(document_backbone.canonical_claim_pool)} 条，章节执行 brief {len(chapter_briefs)} 个。"
                ),
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="document_backbone_ready",
            payload={
                "glossary_count": len(document_backbone.canonical_glossary),
                "claim_count": len(document_backbone.canonical_claim_pool),
                "confusion_count": len(document_backbone.confusion_map),
                "preliminary_kg_node_count": int(preliminary_kg.get("node_count", 0) or 0),
                "preliminary_kg_edge_count": int(preliminary_kg.get("edge_count", 0) or 0),
                "warning_count": len(warnings),
                "fallback_used": document_backbone.fallback_used,
                "chapter_brief_count": len(chapter_briefs),
            },
        )
        return {
            "document_backbone": document_backbone.model_dump(mode="json"),
            "chapter_execution_briefs": [item.model_dump(mode="json") for item in chapter_briefs],
            "chapters_enhanced": chapters_enhanced,
            "dispatch_table": dispatch_table,
            "preliminary_kg": preliminary_kg,
            "guideline": guideline,
            "backbone_conflict_warnings": [item.model_dump(mode="json") for item in warnings],
            "backbone_ms": elapsed_ms,
            "llm_calls_total": 1,
        }

    return document_backbone_node


__all__ = ["build_document_backbone_node"]
