"""Planner graph definition and lane-local runtime entrypoints."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.result import WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.digest.planner.nodes import (
    build_compose_plan_contract_node,
    build_finalize_plan_contract_node,
    build_generate_plan_preview_node,
    build_prepare_material_context_node,
    build_probe_supporting_evidence_node,
    build_summarize_material_digest_node,
)
from app.workflows.digest.planner.state import (
    BuildPlannerGraphInput,
    BuildPlannerGraphOutput,
    BuildPlannerState,
)
from app.workflows.digest.common.contracts import (
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
        "prepare_material_context",
        trace.node(
            build_prepare_material_context_node(context=context),
            name="prepare_material_context",
            timing_field="prepare_ms",
        ),
    )
    workflow.add_node(
        "summarize_material_digest",
        trace.node(
            build_summarize_material_digest_node(context=context),
            name="summarize_material_digest",
            timing_field="digest_ms",
        ),
    )
    workflow.add_node(
        "generate_plan_preview",
        trace.node(
            build_generate_plan_preview_node(context=context),
            name="generate_plan_preview",
            timing_field="preview_ms",
        ),
    )
    workflow.add_node(
        "probe_supporting_evidence",
        trace.node(
            build_probe_supporting_evidence_node(context=context),
            name="probe_supporting_evidence",
            timing_field="probe_ms",
        ),
    )
    workflow.add_node(
        "compose_plan_contract",
        trace.node(
            build_compose_plan_contract_node(context=context),
            name="compose_plan_contract",
            timing_field="compose_ms",
        ),
    )
    workflow.add_node(
        "finalize_plan_contract",
        trace.node(
            build_finalize_plan_contract_node(context=context),
            name="finalize_plan_contract",
            timing_field="finalize_ms",
        ),
    )
    workflow.set_entry_point("prepare_material_context")
    workflow.add_conditional_edges("prepare_material_context", route_after_step, {"continue": "summarize_material_digest", "fail": END})
    workflow.add_conditional_edges("summarize_material_digest", route_after_step, {"continue": "generate_plan_preview", "fail": END})
    workflow.add_conditional_edges("generate_plan_preview", route_after_step, {"continue": "probe_supporting_evidence", "fail": END})
    workflow.add_conditional_edges("probe_supporting_evidence", route_after_step, {"continue": "compose_plan_contract", "fail": END})
    workflow.add_conditional_edges("compose_plan_contract", route_after_step, {"continue": "finalize_plan_contract", "fail": END})
    workflow.add_edge("finalize_plan_contract", END)
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
        "planner_generation_mode": "deep_research_v3",
        "error": None,
    }


def get_langgraph_dev_planner_graph() -> StateGraph:
    return build_planner_graph(context=create_langgraph_dev_context("digest.planner.langgraph_dev"))


async def run_build_planner_workflow(
    *,
    subject: str,
    file_ids: list[int],
    user_goal: str,
    planner_session_id: str,
    digest_mode: str,
    tone: str,
    selected_skillpacks: list[str],
    message_history: list[str],
    latest_plan: dict | None = None,
    progress_callback: object | None = None,
    token_callback: object | None = None,
) -> WorkflowResult[BuildPlannerState]:
    """Run the planner lane and return the final workflow state."""

    context = WorkflowContext(
        workflow_name="digest.planner",
        subject=subject,
        metadata={
            "planner_session_id": planner_session_id,
            "digest_mode": digest_mode,
        },
    )
    return await run_state_graph(
        workflow_name="digest.planner",
        graph_builder=lambda: build_planner_graph(context=context),
        initial_state=create_planner_initial_state(
            subject=subject,
            file_ids=file_ids,
            user_goal=user_goal,
            digest_mode=digest_mode,
            tone=tone,
            selected_skillpacks=selected_skillpacks,
            planner_session_id=planner_session_id,
            message_history=message_history,
            latest_plan=latest_plan,
            progress_callback=progress_callback,
            token_callback=token_callback,
        ),
        context=context,
    )


__all__ = [
    "build_planner_graph",
    "create_planner_initial_state",
    "get_langgraph_dev_planner_graph",
    "route_after_step",
    "run_build_planner_workflow",
]

