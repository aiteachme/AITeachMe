"""Prepare DocGen global seed inputs before chapter-level fan-out."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.file_summaries import (
    derive_source_affinity_and_evidence,
    summarize_files,
)
from app.workflows.digest.docgen.lib.models import DocGenContext, DocGenIntentProfile
from app.workflows.digest.docgen.lib.pipeline_artifacts import (
    build_intent_enhanced,
    build_summary_enhanced,
    build_user_profile_enhanced,
)
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


def _intent_from_confirmed_plan(
    *,
    docgen_context: DocGenContext,
    confirmed_plan: dict,
) -> DocGenIntentProfile:
    """Compile only model-authored Planner semantics and deterministic runtime policy."""

    plan_text = docgen_context.plan or str(confirmed_plan.get("plan") or "")
    goal = docgen_context.user_prompt or str(confirmed_plan.get("user_prompt") or "") or plan_text
    chapters = [item for item in list(confirmed_plan.get("chapters") or []) if isinstance(item, dict)]
    chapter_writing_strategies = [
        str(item.get("writing_instructions") or "").strip()
        for item in chapters
        if str(item.get("writing_instructions") or "").strip()
    ]
    strategy_text = "\n".join(
        [
            text
            for text in [plan_text, *chapter_writing_strategies]
            if text
        ]
    )
    return DocGenIntentProfile(
        learning_goal_text=goal,
        audience_profile_text=docgen_context.learner_profile_text,
        content_strategy_text=strategy_text,
        example_practice_policy="\n".join(chapter_writing_strategies),
        source_usage_policy="本地资料优先；资料不足时明确不确定性，不补写无依据事实",
        teaching_intent=strategy_text or goal,
        example_ratio=0.0,
        practice_ratio=0.0,
        evidence_strictness=0.68,
        review_strictness=0.55,
        # Sprint controls the learning pace and chapter shape; it must not
        # silently downgrade every confirmed course to a compact explanation.
        depth_level="standard",
        explanation_depth="standard",
        avoid_list=["脱离确认方案扩展章节", "无资料依据的断言", "重复解释同一知识点"],
        fallback_used=False,
    )


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
        intent_core_ms = 0
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
            "intent_core_ms": intent_core_ms,
            "file_summary_llm_calls": file_summary_llm_calls,
            "llm_calls_total": file_summary_llm_calls,
        }

    return prepare_global_seed_node


__all__ = ["build_prepare_global_seed_node"]
