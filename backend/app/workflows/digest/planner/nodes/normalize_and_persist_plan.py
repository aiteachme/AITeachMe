"""Normalize the plan contract and persist planner session state."""

from __future__ import annotations

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.models import PlanIntent, PlannerBrief
from app.workflows.digest.planner.lib.plans import normalize_planner_draft
from app.workflows.digest.planner.lib.store import save_planner_result
from app.workflows.digest.planner.prompts import build_subject_name_prompt
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)
_AUTO_TITLE_PLACEHOLDERS = {"", "untitled subject", "新学科", "无标题", "未命名", "未命名学科"}


def _needs_auto_subject_name(state: BuildPlannerState) -> bool:
    return str(state.get("planner_operation") or "") == "create"


def _clean_subject_name(value: str | None) -> str:
    cleaned = str(value or "").strip().strip("\"'“”‘’`，。；;:： ")
    cleaned = " ".join(cleaned.split())
    if not cleaned or cleaned.casefold() in _AUTO_TITLE_PLACEHOLDERS:
        return ""
    return cleaned[:16]


async def _generate_subject_name(state: BuildPlannerState, *, draft) -> str:
    if not _needs_auto_subject_name(state):
        return ""

    material_context = state["material_context"]
    planner_brief = PlannerBrief.model_validate(state.get("planner_brief") or {})
    plan_intent = PlanIntent.model_validate(state.get("plan_intent") or {})
    filenames = [
        packet.filename
        for packet in list(material_context.source_packets or [])[:5]
        if str(packet.filename or "").strip()
    ]
    prompt = build_subject_name_prompt(
        user_prompt=state.get("user_prompt") or "",
        filenames=filenames,
        digest_mode=draft.digest_mode,
        plan_intent=plan_intent.plan_intent,
        plan_summary=draft.plan_summary,
        chapter_titles=[chapter.title for chapter in draft.chapter_plan],
        planner_brief=planner_brief.markdown,
    )
    try:
        title = await acompletion_with_fallback(
            [{"role": "user", "content": prompt}],
            call_purpose=LLMCallPurpose.CLASSIFY,
            model="light",
            max_tokens=40,
            temperature=0.2,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "生成最终学科标题",
            },
        )
    except Exception:
        logger.exception(
            "planner_subject_name_generation_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject") or "",
        )
        return ""
    return _clean_subject_name(title)


def build_normalize_and_persist_plan_node(*, context: WorkflowContext):
    """构建 Planner 保存节点。

    负责把模型输出的 build_plan_draft 规范化成稳定合同，并写入 planner
    session / chat mirror。这里是 Planner 图的最后一步。
    """

    async def normalize_and_persist_plan_node(state: BuildPlannerState) -> dict:
        """保存当前 Planner 草稿并返回 API 响应所需状态。"""

        logger.info(
            "planner_normalize_started",
            planner_session_id=state.get("planner_session_id", ""),
            subject=state.get("subject", ""),
            has_build_plan_draft=bool(state.get("build_plan_draft")),
            state_error=state.get("error"),
        )
        material_context = state["material_context"]
        digest_mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
        # 上一个节点已经完成“生成”；这里把极简 JSON 合同补齐成 API/DocGen 稳定结构并落库。
        draft = normalize_planner_draft(
            state.get("build_plan_draft") or {},
            subject=state["subject"],
            user_prompt=state.get("user_prompt") or "",
            requested_digest_mode=digest_mode,
            shared_inputs=material_context,
            latest_plan=state.get("latest_plan"),
        )
        generated_subject_name = await _generate_subject_name(state, draft=draft)
        if generated_subject_name:
            draft.subject = generated_subject_name
        logger.info(
            "planner_normalize_completed",
            planner_session_id=state.get("planner_session_id", ""),
            chapter_count=len(draft.chapter_plan),
            plan_step_count=len(draft.plan_steps),
            digest_mode=draft.digest_mode,
            plan_summary_chars=len(draft.plan_summary or ""),
            generated_subject_name=generated_subject_name or None,
        )
        plan = draft.model_dump(mode="json")
        outline_items = [
            {
                "title": chapter.title,
                "objective": chapter.objective,
            }
            for chapter in draft.chapter_plan
        ]
        await emit_planner_event(
            state,
            event="planner.plan.ready",
            detail="已提炼出计划大纲，可以确认或继续修改。",
            payload={
                "chapter_count": len(draft.chapter_plan),
                "digest_mode": draft.digest_mode,
                "plan_summary": draft.plan_summary,
                "outline_items": outline_items,
            },
        )
        result = {
            "plan": plan,
            "plan_summary": draft.plan_summary,
            "digest_mode": draft.digest_mode,
            "generated_subject_name": generated_subject_name,
        }
        persist_update = save_planner_result(
            {**state, **result},
            plan=plan,
            material_context=material_context,
        )
        logger.info(
            "planner_persist_completed",
            planner_session_id=state.get("planner_session_id", ""),
            persisted=bool(persist_update),
            planner_turn_count=len(persist_update.get("planner_turns", []) or []),
        )
        return {**result, **persist_update}

    return normalize_and_persist_plan_node


__all__ = ["build_normalize_and_persist_plan_node"]
