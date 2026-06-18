"""Build chapter execution briefs in parallel after backbone construction."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.chapter_execution_brief import (
    build_chapter_execution_brief,
    build_fallback_chapter_execution_brief,
)
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocumentBackbone,
    HighConfidenceEvidenceUnit,
)
from app.workflows.digest.docgen.lib.pipeline_context import learner_profile_text_for_branch
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.prefetch import start_docgen_kg_prefetch


def _bullet_lines(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [f"## {title}", *[f"- {item}" for item in items if str(item or "").strip()], ""]


def _brief_role_lines(role_targets: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for role, targets in sorted(role_targets.items()):
        cleaned = [str(item or "").strip() for item in targets if str(item or "").strip()]
        if not cleaned:
            continue
        lines.append(f"- {role}: " + "；".join(cleaned[:8]))
    return ["## 内容角色目标", *lines, ""] if lines else []


def _plan_lines(title: str, plans: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in plans[:8]:
        target = str(item.get("target") or item.get("knowledge") or item.get("topic") or "").strip()
        purpose = str(item.get("purpose") or item.get("reason") or item.get("type") or "").strip()
        if not target and not purpose:
            continue
        lines.append(f"- {target}" + (f"：{purpose}" if purpose else ""))
    return [f"## {title}", *lines, ""] if lines else []


def _brief_prefetch_chapters(
    *,
    task_seeds: list[ChapterGenerationTaskSeed],
    chapter_briefs: list[dict[str, Any]],
    evidence_units: list[HighConfidenceEvidenceUnit],
) -> list[dict[str, Any]]:
    """Build compact markdown chapters so KG extraction can start at brief time."""

    seed_by_index = {item.chapter_index: item for item in task_seeds}
    chapters: list[dict[str, Any]] = []
    for raw_brief in chapter_briefs:
        brief = ChapterExecutionBrief.model_validate(raw_brief)
        seed = seed_by_index.get(brief.chapter_index)
        title = (
            (seed.enhanced_title if seed is not None else "")
            or (seed.confirmed_title if seed is not None else "")
            or f"第 {brief.chapter_index} 章"
        )
        source_slices = list(seed.source_slices[:8] if seed is not None else [])
        source_file_ids = list(seed.priority_file_ids if seed is not None else [])
        if not source_file_ids:
            source_file_ids = [
                source_slice.file_id
                for source_slice in source_slices
                if source_slice.file_id
            ]
        evidence_lines = [
            item.text
            for item in sorted(
                [evidence for evidence in evidence_units if brief.chapter_index in evidence.chapter_affinity],
                key=lambda evidence: evidence.confidence,
                reverse=True,
            )[:8]
            if item.text
        ]
        source_lines = [
            f"{source_slice.section_title or source_slice.section_ref}: {source_slice.summary or source_slice.excerpt}"
            for source_slice in source_slices
            if source_slice.section_title or source_slice.section_ref or source_slice.summary or source_slice.excerpt
        ]
        markdown_parts = [
            f"# {title}",
            "",
            "## 本章目标",
            str(seed.chapter_goal if seed is not None else "").strip() or title,
            "",
            *_bullet_lines("必须覆盖", list(seed.required_elements if seed is not None else [])),
            *_brief_role_lines(dict(brief.content_role_targets or {})),
            *_bullet_lines("教学提纲", list(brief.teaching_outline)),
            *_bullet_lines("概念目标", list(brief.concept_targets)),
            *_bullet_lines("定义目标", list(brief.definition_targets)),
            *_bullet_lines("公式模型目标", list(brief.formula_targets)),
            *_bullet_lines("例题目标", list(brief.example_targets)),
            *_bullet_lines("易错辨析目标", list(brief.pitfall_targets)),
            *_plan_lines("例题覆盖计划", list(brief.example_coverage_plan)),
            *_plan_lines("章节测试计划", list(brief.chapter_end_practice_plan)),
            *_bullet_lines("高置信资料证据", evidence_lines),
            *_bullet_lines("分配资料切片", source_lines),
        ]
        chapters.append(
            {
                "chapter_index": brief.chapter_index,
                "title": title,
                "summary": str(seed.chapter_goal if seed is not None else "").strip(),
                "markdown": "\n".join(markdown_parts).strip(),
                "source_scope": {"source_file_ids": source_file_ids},
                "source_details": [
                    {
                        "file_id": source_slice.file_id,
                        "filename": source_slice.filename,
                        "section_ref": source_slice.section_ref,
                        "section_title": source_slice.section_title,
                    }
                    for source_slice in source_slices
                ],
            }
        )
    return chapters


def build_chapter_execution_briefs_node(*, context: WorkflowContext):
    """构建章节执行 brief 节点。"""

    async def build_chapter_execution_briefs_node_impl(state: DocGenState) -> dict:
        started_at = perf_counter()
        task_seeds = [
            ChapterGenerationTaskSeed.model_validate(item)
            for item in sorted(
                list(state.get("chapter_task_seeds") or []),
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        if not task_seeds:
            return {"error": "缺少可生成执行 brief 的章节 seed。"}
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        intent_core = dict(state.get("intent_core") or {})
        user_profile = dict(state.get("user_profile") or {})
        evidence_units = [
            HighConfidenceEvidenceUnit.model_validate(item)
            for item in list(state.get("high_confidence_evidence_units") or [])
        ]

        async def _build_one(task_seed: ChapterGenerationTaskSeed) -> dict:
            glossary_terms = [
                item.term
                for item in document_backbone.canonical_glossary
                if task_seed.chapter_index in item.target_chapters and item.term
            ][:4]
            claim_targets = [
                item.claim_text
                for item in document_backbone.canonical_claim_pool
                if item.target_chapter == task_seed.chapter_index and item.claim_text
            ][:4]
            confusion_targets = [
                item.topic or item.contrast
                for item in document_backbone.confusion_map
                if task_seed.chapter_index in item.target_chapters and (item.topic or item.contrast)
            ][:3]
            evidence_items = [
                item.model_dump(mode="json")
                for item in sorted(
                    [
                        evidence
                        for evidence in evidence_units
                        if task_seed.chapter_index in evidence.chapter_affinity
                    ],
                    key=lambda evidence: evidence.confidence,
                    reverse=True,
                )[:8]
            ]
            learner_profile_text = learner_profile_text_for_branch(
                docgen_context_text=docgen_context.learner_profile_text,
                state_profile_text=str(state.get("learner_profile_text") or ""),
                user_profile=user_profile,
            ).strip()
            chapter_payload = {
                "chapter_index": task_seed.chapter_index,
                "title": task_seed.confirmed_title,
                "resolved_title": task_seed.enhanced_title,
                "objective": task_seed.chapter_goal,
                "required_elements": task_seed.required_elements,
            }
            source_slice_payloads = [item.model_dump(mode="json") for item in task_seed.source_slices[:8]]
            locked_title = task_seed.enhanced_title or task_seed.confirmed_title
            brief_error = ""
            try:
                brief = await build_chapter_execution_brief(
                    course_name=docgen_context.course_name,
                    digest_mode=docgen_context.digest_mode,
                    chapter=chapter_payload,
                    locked_title=locked_title,
                    intent_core=intent_core,
                    glossary_terms=glossary_terms,
                    claim_targets=claim_targets,
                    confusion_targets=confusion_targets,
                    source_slices=source_slice_payloads,
                    evidence_items=evidence_items,
                    plan=docgen_context.plan,
                    docgen_history_brief=docgen_context.docgen_history_brief,
                    learner_profile_text=learner_profile_text,
                    extra_metadata={
                        "build_session_id": state.get("build_session_id") or "",
                        "planner_session_id": state.get("planner_session_id") or "",
                        "confirmed_plan_id": state.get("confirmed_plan_id") or "",
                        "chapter_index": task_seed.chapter_index,
                    },
                )
            except Exception as exc:
                brief_error = str(exc)
                brief = build_fallback_chapter_execution_brief(
                    course_name=docgen_context.course_name,
                    chapter=chapter_payload,
                    locked_title=locked_title,
                    glossary_terms=glossary_terms,
                    claim_targets=claim_targets,
                    confusion_targets=confusion_targets,
                    source_slices=source_slice_payloads,
                    evidence_items=evidence_items,
                )
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                event={
                    "stage": "chapter_execution_brief_fallback" if brief.fallback_used else "chapter_execution_brief_ready",
                    "chapter_index": task_seed.chapter_index,
                    "summary": (
                        f"第 {task_seed.chapter_index} 章执行 brief 使用本地计划兜底生成，流程继续。"
                        if brief.fallback_used
                        else f"第 {task_seed.chapter_index} 章执行 brief 已生成。"
                    ),
                    "detail": brief_error,
                    "created_at": utcnow(),
                },
            )
            return brief.model_dump(mode="json")

        chapter_briefs = await run_llm_tasks(
            task_seeds,
            _build_one,
        )
        chapter_briefs.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
        kg_prefetch_started = start_docgen_kg_prefetch(
            course_id=state["course_id"],
            build_session_id=state.get("build_session_id", ""),
            chapters=_brief_prefetch_chapters(
                task_seeds=task_seeds,
                chapter_briefs=chapter_briefs,
                evidence_units=evidence_units,
            ),
            document_backbone=state.get("document_backbone") or {},
            docgen_manifest={
                "intent_profile": dict(state.get("intent_profile") or state.get("intent_core") or {}),
                "intent_enhanced": dict(state.get("intent_enhanced") or {}),
                "summary_enhanced": dict(state.get("summary_enhanced") or {}),
                "user_profile": dict(state.get("user_profile") or {}),
                "chapters_enhanced": list(state.get("chapters_enhanced") or []),
                "chapter_task_seeds": [item.model_dump(mode="json") for item in task_seeds],
                "chapter_execution_briefs": list(chapter_briefs),
                "document_backbone_snapshot": dict(state.get("document_backbone") or {}),
                "guideline": dict(state.get("guideline") or {}),
                "dispatch_table": dict(state.get("dispatch_table") or {}),
                "preliminary_kg": dict(state.get("preliminary_kg") or {}),
                "digest_mode": str(state.get("digest_mode") or ""),
                "kg_prefetch_phase": "chapter_briefs",
            },
        )
        if kg_prefetch_started:
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                event={
                    "stage": "kg_prefetch_started_from_chapter_briefs",
                    "summary": "章节 brief 已生成，知识图谱早期抽取已同步启动。",
                    "created_at": utcnow(),
                },
            )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_execution_briefs_ready",
            payload={
                "chapter_count": len(chapter_briefs),
                "fallback_count": sum(1 for item in chapter_briefs if bool(item.get("fallback_used", False))),
                "kg_prefetch_started": kg_prefetch_started,
                "kg_prefetch_phase": "chapter_briefs" if kg_prefetch_started else "",
            },
        )
        return {
            "chapter_execution_briefs": chapter_briefs,
            "kg_prefetch_status": "started_from_chapter_briefs" if kg_prefetch_started else "not_started_from_chapter_briefs",
            "kg_prefetch_ready": False,
            "chapter_prepare_ms": elapsed_ms,
            "llm_calls_total": len(chapter_briefs),
        }

    return build_chapter_execution_briefs_node_impl


__all__ = ["build_chapter_execution_briefs_node"]
