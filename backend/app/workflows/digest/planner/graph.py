"""Planner graph."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.model_router import TaskType
from app.workflows.common.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.digest.observability import wrap_digest_node
from app.workflows.digest.planner.models import BuildPlannerDraft, build_fallback_plan
from app.workflows.digest.prompts import build_planner_prompt
from app.workflows.digest.planner.state import BuildPlannerState
from app.workflows.digest.shared.prepare import prepare_shared_inputs


def build_planner_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(BuildPlannerState)
    workflow.add_node(
        "load_context",
        wrap_digest_node(
            build_load_context_node(context=context),
            workflow_name=context.workflow_name,
            lane="planner",
            node_name="load_context",
        ),
    )
    workflow.add_node(
        "draft_plan",
        wrap_digest_node(
            build_draft_plan_node(context=context),
            workflow_name=context.workflow_name,
            lane="planner",
            node_name="draft_plan",
        ),
    )
    workflow.set_entry_point("load_context")
    workflow.add_conditional_edges("load_context", route_after_step, {"continue": "draft_plan", "fail": END})
    workflow.add_edge("draft_plan", END)
    return workflow


def route_after_step(state: BuildPlannerState) -> str:
    return "fail" if state.get("error") else "continue"


def build_load_context_node(*, context: WorkflowContext):
    async def load_context_node(state: BuildPlannerState) -> dict:
        shared_inputs = await prepare_shared_inputs(
            state["subject"],
            state.get("file_ids", []),
            user_prompt=state.get("user_goal"),
        )
        if not shared_inputs.source_packets:
            return {"error": "No parsed source files are available for planning."}
        return {
            "shared_inputs": shared_inputs,
            "digest_mode": state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value,
            "tone": state.get("tone") or "encouraging",
        }

    return load_context_node


def build_draft_plan_node(*, context: WorkflowContext):
    async def draft_plan_node(state: BuildPlannerState) -> dict:
        shared_inputs = state["shared_inputs"]
        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
        tone = state.get("tone") or "encouraging"
        prompt = build_planner_prompt(
            subject=state["subject"],
            user_goal=state.get("user_goal") or "",
            digest_mode=digest_mode,
            tone=tone,
            shared_inputs=shared_inputs,
            message_history=list(state.get("message_history", [])),
            latest_plan=state.get("latest_plan"),
        )
        try:
            draft = await acompletion_with_fallback(
                [{"role": "user", "content": prompt}],
                task_type=TaskType.REASONING,
                tier="strategic",
                response_model=BuildPlannerDraft,
                extra_metadata={"planner_session_id": state.get("planner_session_id", "")},
            )
        except Exception:
            draft = build_fallback_plan(
                subject=state["subject"],
                user_goal=state.get("user_goal") or "",
                digest_mode=digest_mode,
                tone=tone,
                shared_inputs=shared_inputs,
            )
        plan = draft.model_dump(mode="json")
        return {"plan": plan, "plan_summary": draft.plan_summary, "digest_mode": draft.digest_mode, "tone": draft.tone}

    return draft_plan_node


def create_planner_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_goal: str,
    digest_mode: str,
    tone: str,
    planner_session_id: str,
    message_history: list[str],
    latest_plan: dict | None = None,
) -> BuildPlannerState:
    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_goal": user_goal,
        "digest_mode": digest_mode,
        "tone": tone,
        "planner_session_id": planner_session_id,
        "message_history": message_history,
        "latest_plan": latest_plan,
        "error": None,
    }


def get_langgraph_dev_planner_graph() -> StateGraph:
    return build_planner_graph(context=create_langgraph_dev_context("digest.planner.langgraph_dev"))


__all__ = ["build_planner_graph", "create_planner_initial_state"]
