"""Compose a structured build plan from sketch, intent and evidence."""

from __future__ import annotations

import structlog

from app.shared.infra.llm_support import acompletion_stream, acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event, emit_planner_token
from app.workflows.digest.planner.lib.plans import BuildPlannerDraft, build_fallback_plan
from app.workflows.digest.planner.lib.models import EvidenceBrief, LearningIntent, PlannerBrief
from app.workflows.digest.planner.prompts import build_plan_composer_messages, build_plan_outline_stream_prompt
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


async def _stream_visible_plan_outline(
    state: BuildPlannerState,
    *,
    material_context,
    planner_brief: PlannerBrief,
    intent: LearningIntent,
    evidence: EvidenceBrief,
) -> str:
    tokens: list[str] = []
    try:
        await emit_planner_token(state, "\n\n")
        stream = acompletion_stream(
            [
                {
                    "role": "user",
                    "content": build_plan_outline_stream_prompt(
                        subject=state["subject"],
                        user_goal=state.get("user_goal") or "",
                        digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                        material_context=material_context,
                        planner_brief=planner_brief,
                        learning_intent=intent,
                        evidence_brief=evidence,
                    ),
                }
            ],
            task_type=TaskType.DOCGEN_LIGHT,
            model="primary",
            temperature=0.15,
            max_tokens=520,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "stream_visible_plan_outline",
            },
        )
        async for token in stream:
            tokens.append(token)
            await emit_planner_token(state, token)
            await emit_planner_event(
                state,
                event="planner.plan.delta",
                detail="计划大纲生成中...",
                payload={"token": token},
            )
    except Exception:
        logger.exception(
            "planner_visible_outline_stream_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state.get("subject") or "",
        )
        return ""
    return "".join(tokens).strip()


def build_compose_build_plan_node(*, context: WorkflowContext):
    del context

    async def compose_build_plan_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        planner_brief = PlannerBrief.model_validate(state.get("planner_brief") or {})
        intent = LearningIntent.model_validate(state.get("learning_intent") or {})
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
            detail="正在把思考过程提炼成几条可确认的计划大纲...",
        )
        visible_outline = await _stream_visible_plan_outline(
            state,
            material_context=material_context,
            planner_brief=planner_brief,
            intent=intent,
            evidence=evidence,
        )
        try:
            draft = await acompletion_with_fallback(
                build_plan_composer_messages(
                    subject=state["subject"],
                    user_goal=state.get("user_goal") or "",
                    digest_mode=state.get("digest_mode") or material_context.course_mode_decision.mode.value,
                    tone=state.get("tone") or "encouraging",
                    material_context=material_context,
                    planner_brief=planner_brief,
                    learning_intent=intent,
                    evidence_brief=evidence,
                    message_history=list(state.get("message_history", [])),
                    latest_plan=state.get("latest_plan"),
                ),
                task_type=TaskType.DOCGEN_LIGHT,
                model="primary",
                response_model=BuildPlannerDraft,
                temperature=0.15,
                max_tokens=1700,
                extra_metadata={
                    "planner_session_id": state.get("planner_session_id") or "",
                    "substep": "compose_build_plan",
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
            "build_plan_draft": draft.model_dump(mode="json"),
            "plan_outline_markdown": visible_outline,
            "generation_mode": "research_surface_v4",
        }

    return compose_build_plan_node


__all__ = ["build_compose_build_plan_node"]
