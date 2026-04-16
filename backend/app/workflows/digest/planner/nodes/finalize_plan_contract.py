"""Finalize and normalize Planner V3 plan contract."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.common.contracts import resolve_planner_retrieval_profile
from app.workflows.digest.planner.lib.finalize_contract import apply_plan_sketch_preferences
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.plans import (
    _resolve_subject_display_name,
    normalize_planner_draft,
)
from app.workflows.digest.planner.lib.models import PlanSketch
from app.workflows.digest.planner.state import BuildPlannerState


def build_finalize_plan_contract_node(*, context: WorkflowContext):
    async def finalize_plan_contract_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        plan_sketch = PlanSketch.model_validate(state.get("plan_sketch") or {})
        digest_mode = state.get("digest_mode") or material_context.course_mode_decision.mode.value
        tone = state.get("tone") or "encouraging"
        draft = normalize_planner_draft(
            state.get("build_plan_contract") or {},
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
        draft = apply_plan_sketch_preferences(
            draft,
            plan_sketch=plan_sketch,
            user_goal=state.get("user_goal") or "",
            subject_display_name=display_subject,
        )
        plan = draft.model_dump(mode="json")
        outline_items = [
            {
                "title": chapter.title,
                "objective": chapter.objective,
            }
            for chapter in draft.chapter_plan[:8]
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
        return {
            "plan": plan,
            "plan_summary": draft.plan_summary,
            "digest_mode": draft.digest_mode,
            "retrieval_profile": resolve_planner_retrieval_profile(),
            "tone": draft.tone,
            "selected_skillpacks": list(draft.selected_skillpacks),
            "planner_generation_mode": state.get("planner_generation_mode") or "deep_research_v3",
        }

    return finalize_plan_contract_node


__all__ = ["build_finalize_plan_contract_node"]
