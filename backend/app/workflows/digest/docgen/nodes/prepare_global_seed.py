"""Prepare DocGen global seed inputs before chapter-level fan-out."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.file_summaries import derive_source_affinity_and_evidence, summarize_files
from app.workflows.digest.docgen.lib.intent import infer_intent_core
from app.workflows.digest.docgen.lib.models import DocGenContext
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_prepare_global_seed_node(*, context: WorkflowContext):
    """构建 DocGen 全局轻准备节点。"""

    async def prepare_global_seed_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        confirmed_plan = dict(state.get("confirmed_plan") or {})
        chapters = list(state.get("chapter_assignments") or [])
        if not chapters:
            return {"error": "DocGen 缺少可执行章节，无法准备全局种子上下文。"}

        update_knowledge_build_status(
            state["subject_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="preparing_docgen_global_seed",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在准备 DocGen 全局种子：文档级意图与文件摘要。",
        )
        append_knowledge_build_recent_event(
            state["subject_id"],
            requested_at=state["requested_at"],
            event={
                "stage": "preparing_docgen_global_seed",
                "summary": "开始准备 DocGen 全局种子：推断文档级意图并摘要文件材料。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_global_seed_started",
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

        async def _run_intent_core():
            step_started_at = perf_counter()
            result = await infer_intent_core(
                subject_name=docgen_context.subject_name,
                digest_mode=docgen_context.digest_mode,
                user_prompt=docgen_context.user_prompt,
                plan_summary=docgen_context.plan_summary or str(confirmed_plan.get("plan_summary") or ""),
                material_profile=material_profile,
                chapters=chapters,
                docgen_history_brief=docgen_context.docgen_history_brief,
                extra_metadata=extra,
            )
            return result, int((perf_counter() - step_started_at) * 1000)

        async def _run_file_summaries():
            result = await (
                summarize_files(
                    shared_inputs,
                    chapters=chapters,
                    digest_mode=docgen_context.digest_mode,
                    extra_metadata=extra,
                )
                if shared_inputs is not None
                else asyncio.sleep(0, result=[])
            )
            return result

        (intent_core, intent_core_ms), file_summaries = await asyncio.gather(
            _run_intent_core(),
            _run_file_summaries(),
        )
        if shared_inputs is not None:
            source_affinity, evidence_units = derive_source_affinity_and_evidence(
                shared_inputs,
                summaries=file_summaries,
                chapters=chapters,
            )
        else:
            source_affinity, evidence_units = [], []
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        append_knowledge_build_recent_event(
            state["subject_id"],
            requested_at=state["requested_at"],
            event={
                "stage": "docgen_global_seed_ready",
                "summary": f"DocGen 全局种子准备完成：意图推断 1 次，文件摘要 {len(file_summaries)} 份。",
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
        return {
            "intent_core": intent_core.model_dump(mode="json"),
            "intent_profile": intent_core.model_dump(mode="json"),
            "file_summaries": [item.model_dump(mode="json") for item in file_summaries],
            "source_affinity_by_chapter": [item.model_dump(mode="json") for item in source_affinity],
            "high_confidence_evidence_units": [item.model_dump(mode="json") for item in evidence_units],
            "prepare_ms": elapsed_ms,
            "intent_core_ms": intent_core_ms,
            "llm_calls_total": 1 + len(file_summaries),
        }

    return prepare_global_seed_node


__all__ = ["build_prepare_global_seed_node"]
