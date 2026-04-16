"""Compose a structured build plan from sketch, intent and evidence."""

from __future__ import annotations

import asyncio

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.plans import BuildPlannerDraft, build_fallback_plan
from app.workflows.digest.planner.lib.research_probe import EvidenceBrief, LearningIntentProfile, PlanSketch
from app.workflows.digest.planner.prompts import build_plan_composer_messages
from app.workflows.digest.planner.state import BuildPlannerState


def build_compose_build_plan_node(*, context: WorkflowContext):
    async def compose_build_plan_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        plan_sketch = PlanSketch.model_validate(state.get("plan_sketch") or {})
        intent = LearningIntentProfile.model_validate(state.get("learning_intent_profile") or {})
        evidence = EvidenceBrief.model_validate(state.get("evidence_brief") or {})
        fallback = build_fallback_plan(
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
            tone=state.get("tone") or "encouraging",
            shared_inputs=material_context,
        )
        await emit_planner_event(
            state,
            event="planner.plan.composing",
            detail="正在综合草稿、意图和证据生成最终大纲...",
        )
        try:
            draft = await acompletion_with_fallback(
                build_plan_composer_messages(
                    subject=state["subject"],
                    user_goal=state.get("user_goal") or "",
                    digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                    tone=state.get("tone") or "encouraging",
                    material_context=material_context,
                    plan_sketch=plan_sketch,
                    intent_profile=intent,
                    evidence_brief=evidence,
                ),
                task_type=TaskType.REASONING,
                tier="reason",
                response_model=BuildPlannerDraft,
                temperature=0.15,
                max_tokens=1800,
                extra_metadata={
                    "planner_session_id": state.get("planner_session_id") or "",
                    "substep": "compose_plan_contract",
                },
            )
        except Exception:
            await emit_planner_event(
                state,
                event="planner.fallback.used",
                detail="最终大纲合成失败，已使用规则构建方案继续。",
            )
            draft = fallback
        return {
            "build_plan_contract": draft.model_dump(mode="json"),
            "planner_generation_mode": "deep_research_v3",
        }

    return compose_build_plan_node


__all__ = ["build_compose_build_plan_node"]
