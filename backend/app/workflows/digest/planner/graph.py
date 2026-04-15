"""Planner graph definition and graph-local bootstrap helpers."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.digest.planner.nodes import (
    build_draft_plan_node,
    build_ground_concepts_node,
    build_load_context_node,
)
from app.workflows.digest.planner.state import (
    BuildPlannerGraphInput,
    BuildPlannerGraphOutput,
    BuildPlannerState,
)
from app.workflows.digest.shared.contracts import (
    resolve_digest_course_type,
    resolve_planner_retrieval_profile,
)


def build_planner_graph(*, context: WorkflowContext) -> StateGraph:
    trace = workflow_tracer(context=context, lane="planner")
    workflow = StateGraph(
        BuildPlannerState,
        input_schema=BuildPlannerGraphInput,
        output_schema=BuildPlannerGraphOutput,
    )
    workflow.add_node(
        "load_context",
        trace.node(
            build_load_context_node(context=context),
            name="load_context",
            timing_field="load_ms",
        ),
    )
    workflow.add_node(
        "ground_concepts",
        trace.node(
            build_ground_concepts_node(context=context),
            name="ground_concepts",
            timing_field="ground_ms",
        ),
    )
    workflow.add_node(
        "draft_plan",
        trace.node(
            build_draft_plan_node(context=context),
            name="draft_plan",
            timing_field="draft_ms",
        ),
    )
    workflow.set_entry_point("load_context")
    workflow.add_conditional_edges("load_context", route_after_step, {"continue": "ground_concepts", "fail": END})
    workflow.add_conditional_edges("ground_concepts", route_after_step, {"continue": "draft_plan", "fail": END})
    workflow.add_edge("draft_plan", END)
    return workflow


def route_after_step(state: BuildPlannerState) -> str:
    return "fail" if state.get("error") else "continue"


def create_planner_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_goal: str,
    digest_mode: str,
    tone: str,
    selected_skillpacks: list[str],
    planner_session_id: str,
    message_history: list[str],
    latest_plan: dict | None = None,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> BuildPlannerState:
    course_type = resolve_digest_course_type(digest_mode)
    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_goal": user_goal,
        "digest_mode": digest_mode,
        "course_type": course_type,
        "retrieval_profile": resolve_planner_retrieval_profile(),
        "teaching_action": "plan_course",
        "tone": tone,
        "selected_skillpacks": list(selected_skillpacks),
        "planner_session_id": planner_session_id,
        "message_history": message_history,
        "latest_plan": latest_plan,
        "progress_callback": progress_callback,
        "token_callback": token_callback,
        "error": None,
    }


def get_langgraph_dev_planner_graph() -> StateGraph:
    return build_planner_graph(context=create_langgraph_dev_context("digest.planner.langgraph_dev"))


__all__ = [
    "build_planner_graph",
    "create_planner_initial_state",
    "get_langgraph_dev_planner_graph",
    "route_after_step",
]

