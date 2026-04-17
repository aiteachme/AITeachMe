"""Normalize the plan contract and persist planner session state."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.finalize_contract import apply_planner_brief_preferences
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.plans import (
    _resolve_subject_display_name,
    normalize_planner_draft,
)
from app.workflows.digest.planner.lib.models import PlannerBrief
from app.workflows.digest.planner.lib.store import save_planner_result
from app.workflows.digest.planner.state import BuildPlannerState


def build_normalize_and_persist_plan_node(*, context: WorkflowContext):
    async def normalize_and_persist_plan_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        planner_brief = PlannerBrief.model_validate(state.get("planner_brief") or {})
        digest_mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
        tone = state.get("tone") or "encouraging"
        # LLM 输出只当草稿看。normalize_planner_draft 会合并 latest_plan /
        # fallback，并收敛成稳定的 ConfirmedPlan 形状。
        draft = normalize_planner_draft(
            state.get("build_plan_draft") or {},
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            requested_digest_mode=digest_mode,
            requested_tone=tone,
            selected_skillpacks=list(state.get("selected_skillpacks") or []),
            shared_inputs=material_context,
            latest_plan=state.get("latest_plan"),
        )
        display_subject = _resolve_subject_display_name(
            state["subject"],
            shared_inputs=material_context,
            user_goal=state.get("user_goal") or "",
        )
        draft = apply_planner_brief_preferences(
            draft,
            planner_brief=planner_brief,
            user_goal=state.get("user_goal") or "",
            subject_display_name=display_subject,
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
            "tone": draft.tone,
            "selected_skillpacks": list(draft.selected_skillpacks),
            "generation_mode": state.get("generation_mode") or "raw_context_three_call_no_retrieval_v6",
        }
        # 只有最终 plan 合同稳定后才落库。直接调图调试会跳过 DB 写入；
        # API create/append 会保存 latest_plan 和 assistant turn。
        persist_update = save_planner_result(
            {**state, **result},
            plan=plan,
            material_context=material_context,
        )
        return {**result, **persist_update}

    return normalize_and_persist_plan_node


__all__ = ["build_normalize_and_persist_plan_node"]
