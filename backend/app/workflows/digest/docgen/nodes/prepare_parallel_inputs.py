"""Prepare DocGen 0A/0B/0C inputs in parallel."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.file_summaries import derive_source_affinity_and_evidence, summarize_files
from app.workflows.digest.docgen.lib.intent import infer_docgen_intent
from app.workflows.digest.docgen.lib.models import DocGenContext
from app.workflows.digest.docgen.lib.outline_enhance import enhance_plan_outline
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_prepare_parallel_inputs_node(*, context: WorkflowContext):
    async def prepare_parallel_inputs_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        confirmed_plan = dict(state.get("confirmed_plan") or {})
        chapters = list(state.get("chapter_assignments") or [])
        if not chapters:
            return {"error": "DocGen 缺少可执行章节，无法准备章节生成上下文。"}

        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="preparing_docgen_context",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在并行增强大纲、识别写作意图并摘要文件材料。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "preparing_docgen_context",
                "summary": "开始并行准备 DocGen 写作上下文：大纲增强、意图识别、文件摘要。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_context_started",
            payload={"chapter_count": len(chapters), "file_count": len(getattr(state.get("shared_inputs"), "source_packets", []) or [])},
        )

        extra = {
            "build_session_id": state.get("build_session_id") or "",
            "planner_session_id": state.get("planner_session_id") or "",
            "confirmed_plan_id": state.get("confirmed_plan_id") or "",
            "digest_mode": state.get("digest_mode") or "",
        }
        material_profile = {}
        shared_inputs = state.get("shared_inputs")
        if shared_inputs is not None and getattr(shared_inputs, "material_profile", None) is not None:
            material_profile = shared_inputs.material_profile.model_dump(mode="json")

        outline_result, intent_profile, file_summaries = await asyncio.gather(
            enhance_plan_outline(
                subject=state["subject"],
                digest_mode=docgen_context.digest_mode,
                user_goal=docgen_context.user_goal,
                plan_summary=docgen_context.plan_summary or str(confirmed_plan.get("plan_summary") or ""),
                chapters=chapters,
                docgen_history_brief=docgen_context.docgen_history_brief,
                extra_metadata=extra,
            ),
            infer_docgen_intent(
                subject=state["subject"],
                digest_mode=docgen_context.digest_mode,
                user_goal=docgen_context.user_goal,
                plan_summary=docgen_context.plan_summary or str(confirmed_plan.get("plan_summary") or ""),
                material_profile=material_profile,
                chapters=chapters,
                docgen_history_brief=docgen_context.docgen_history_brief,
                extra_metadata=extra,
            ),
            summarize_files(
                shared_inputs,
                chapters=chapters,
                digest_mode=docgen_context.digest_mode,
                extra_metadata=extra,
            ) if shared_inputs is not None else asyncio.sleep(0, result=[]),
        )
        enhanced_outlines, mismatch_warnings = outline_result
        if shared_inputs is not None:
            source_affinity, evidence_units = derive_source_affinity_and_evidence(
                shared_inputs,
                summaries=file_summaries,
                chapters=chapters,
            )
        else:
            source_affinity, evidence_units = [], []
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_context_ready",
            payload={
                "chapter_count": len(enhanced_outlines),
                "file_summary_count": len(file_summaries),
                "evidence_candidate_count": len(evidence_units),
                "intent_fallback_used": bool(intent_profile.fallback_used),
                "mismatch_warning_count": len(mismatch_warnings),
            },
        )
        return {
            "enhanced_chapter_outlines": [item.model_dump(mode="json") for item in enhanced_outlines],
            "intent_profile": intent_profile.model_dump(mode="json"),
            "file_summaries": [item.model_dump(mode="json") for item in file_summaries],
            "source_affinity_by_chapter": [item.model_dump(mode="json") for item in source_affinity],
            "high_confidence_evidence_units": [item.model_dump(mode="json") for item in evidence_units],
            "plan_mismatch_warnings": list(mismatch_warnings),
            "prepare_ms": elapsed_ms,
            "llm_calls_total": 2 + len(file_summaries),
        }

    return prepare_parallel_inputs_node


__all__ = ["build_prepare_parallel_inputs_node"]
