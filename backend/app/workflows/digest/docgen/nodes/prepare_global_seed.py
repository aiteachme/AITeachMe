"""Prepare DocGen global seed inputs before chapter-level fan-out."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.file_summaries import derive_source_affinity_and_evidence, summarize_files
from app.workflows.digest.docgen.lib.intent import infer_intent_core
from app.workflows.digest.docgen.lib.models import DocGenContext, DocGenIntentProfile
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _intent_payload_for_state(intent_core: DocGenIntentProfile) -> dict:
    raw = intent_core.model_dump(mode="json")
    legacy_keys = {
        "document_style",
        "depth_level",
        "explanation_depth",
        "example_preference",
        "definition_depth",
        "exam_orientation",
        "review_orientation",
        "chapter_style_hints",
    }
    legacy = {key: raw.get(key) for key in legacy_keys if key in raw}
    return {
        "learning_goal_text": raw.get("learning_goal_text", ""),
        "audience_profile_text": raw.get("audience_profile_text", ""),
        "content_strategy_text": raw.get("content_strategy_text", ""),
        "example_practice_policy": raw.get("example_practice_policy", ""),
        "source_usage_policy": raw.get("source_usage_policy", ""),
        "teaching_intent": raw.get("teaching_intent", ""),
        "example_ratio": raw.get("example_ratio", 0.0),
        "practice_ratio": raw.get("practice_ratio", 0.0),
        "evidence_strictness": raw.get("evidence_strictness", 0.0),
        "review_strictness": raw.get("review_strictness", 0.0),
        "avoid_list": raw.get("avoid_list", []),
        "fallback_used": raw.get("fallback_used", False),
        "legacy_compat": legacy,
    }


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
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="preparing_docgen_global_seed",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在准备 DocGen 全局种子：文档级意图与文件摘要。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
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
                course_name=docgen_context.course_name,
                digest_mode=docgen_context.digest_mode,
                user_prompt=docgen_context.user_prompt,
                plan=docgen_context.plan or str(confirmed_plan.get("plan") or ""),
                material_profile=material_profile,
                chapters=chapters,
                docgen_history_brief=docgen_context.docgen_history_brief,
                extra_metadata=extra,
            )
            return result, int((perf_counter() - step_started_at) * 1000)

        async def _run_file_summaries():
            if shared_inputs is None:
                return []
            return await summarize_files(
                shared_inputs,
                chapters=chapters,
                digest_mode=docgen_context.digest_mode,
                extra_metadata=extra,
            )

        (intent_core, intent_core_ms), file_summaries = await run_llm_tasks(
            [_run_intent_core, _run_file_summaries],
            lambda task: task(),
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
        intent_payload = _intent_payload_for_state(intent_core)
        return {
            "intent_core": intent_payload,
            "intent_profile": intent_payload,
            "file_summaries": [item.model_dump(mode="json") for item in file_summaries],
            "source_affinity_by_chapter": [item.model_dump(mode="json") for item in source_affinity],
            "high_confidence_evidence_units": [item.model_dump(mode="json") for item in evidence_units],
            "prepare_ms": elapsed_ms,
            "intent_core_ms": intent_core_ms,
            "file_summary_llm_calls": file_summary_llm_calls,
            "llm_calls_total": 1 + file_summary_llm_calls,
        }

    return prepare_global_seed_node


__all__ = ["build_prepare_global_seed_node"]
