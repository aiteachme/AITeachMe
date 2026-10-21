"""Build the multimodal global seed with visual-aware source routing."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.file_summaries import derive_source_affinity_and_evidence
from app.workflows.digest.docgen.lib.models import DocGenContext
from app.workflows.digest.docgen.lib.pipeline_artifacts import (
    build_intent_enhanced,
    build_summary_enhanced,
    build_user_profile_enhanced,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.nodes.prepare_global_seed import (
    _intent_from_confirmed_plan,
    _intent_payload_for_state,
)
from app.workflows.digest.docgen_multimodal.lib.file_summaries import summarize_files
from app.workflows.digest.docgen_multimodal.state import MultimodalDocGenState


def build_prepare_global_seed_node(*, context: WorkflowContext):
    """Prepare DocGen seed; only the file-summary LLM sees visual descriptions."""

    async def prepare_global_seed_node(state: MultimodalDocGenState) -> dict:
        started_at = perf_counter()
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        confirmed_plan = dict(state.get("confirmed_plan") or {})
        chapters = list(state.get("chapter_assignments") or [])
        if not chapters:
            return {"error": "DocGen 缺少可执行章节，无法准备全局种子上下文。"}

        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            status="running",
            stage="preparing_docgen_global_seed",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在准备 DocGen 全局种子：文档级意图与文件摘要。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={
                "stage": "preparing_docgen_global_seed",
                "summary": "开始准备 DocGen 全局种子：读取确认方案并语义路由文件材料。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_global_seed_started",
            payload={"chapter_count": len(chapters), "file_count": len(getattr(state.get("shared_inputs"), "source_packets", []) or [])},
        )

        material_profile = {}
        shared_inputs = state.get("shared_inputs")
        if shared_inputs is not None and getattr(shared_inputs, "material_profile", None) is not None:
            material_profile = shared_inputs.material_profile.model_dump(mode="json")

        intent_core = _intent_from_confirmed_plan(
            docgen_context=docgen_context,
            confirmed_plan=confirmed_plan,
        )
        extra = {
            "build_session_id": state.get("build_session_id") or "",
            "planner_session_id": state.get("planner_session_id") or "",
            "confirmed_plan_id": state.get("confirmed_plan_id") or "",
            "digest_mode": state.get("digest_mode") or "",
        }
        file_summaries = (
            await summarize_files(
                shared_inputs,
                chapters=chapters,
                digest_mode=docgen_context.digest_mode,
                visual_evidence_items=state.get("visual_evidence_items") or [],
                extra_metadata=extra,
            )
            if shared_inputs is not None
            else []
        )
        if shared_inputs is not None:
            source_affinity, evidence_units = derive_source_affinity_and_evidence(
                shared_inputs,
                summaries=file_summaries,
                chapters=chapters,
            )
        else:
            source_affinity, evidence_units = [], []
        file_summary_llm_calls = sum(int(getattr(item, "llm_call_count", 0) or 0) for item in file_summaries)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={
                "stage": "docgen_global_seed_ready",
                "summary": f"DocGen 全局种子准备完成：已复用确认方案，语义路由资料 {len(file_summaries)} 份。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_global_seed_ready",
            payload={
                "chapter_count": len(chapters),
                "file_summary_count": len(file_summaries),
                "evidence_candidate_count": len(evidence_units),
                "intent_fallback_used": bool(intent_core.fallback_used),
            },
        )
        intent_payload = _intent_payload_for_state(intent_core)
        intent_enhanced = build_intent_enhanced(
            intent_core=intent_payload,
            docgen_context=docgen_context,
            chapters=chapters,
            material_profile=material_profile,
            source_affinity_by_chapter=source_affinity,
            high_confidence_evidence_units=evidence_units,
        )
        summary_enhanced = build_summary_enhanced(
            file_summaries=file_summaries,
            source_affinity_by_chapter=source_affinity,
            high_confidence_evidence_units=evidence_units,
        )
        user_profile = build_user_profile_enhanced(docgen_context=docgen_context)
        return {
            "intent_core": intent_payload,
            "intent_profile": intent_payload,
            "intent_enhanced": intent_enhanced,
            "user_profile": user_profile,
            "file_summaries": [item.model_dump(mode="json") for item in file_summaries],
            "summary_enhanced": summary_enhanced,
            "source_affinity_by_chapter": [item.model_dump(mode="json") for item in source_affinity],
            "high_confidence_evidence_units": [item.model_dump(mode="json") for item in evidence_units],
            "prepare_ms": elapsed_ms,
            "intent_core_ms": 0,
            "file_summary_llm_calls": file_summary_llm_calls,
            "llm_calls_total": file_summary_llm_calls,
        }

    return prepare_global_seed_node


__all__ = ["build_prepare_global_seed_node"]
