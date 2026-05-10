"""Profile study-plan graph definition and runtime entrypoint.

This lane generates actionable study-plan suggestions from profile signals.
It is intentionally named ``study_plan`` to avoid confusion with
``digest/planner``, which plans source-material digestion and document shape.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.shared.infra.workflow.result import WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.profile.common import ProfileNodeTracer, profile_dev_context, route_after_error
from app.workflows.profile.pipeline.prompts import PROMPTS
from app.workflows.profile.study_plan.nodes import (
    build_load_profile_context_node,
    build_study_plan_node,
    fail_study_plan_node,
)
from app.workflows.profile.study_plan.state import ProfileStudyPlanState

PROFILE_STUDY_PLAN_WORKFLOW_NAME = "profile.study_plan"

NODE_LOAD_PROFILE_CONTEXT = "load_profile_context"
NODE_BUILD_STUDY_PLAN = "build_study_plan"
NODE_FAIL_STUDY_PLAN = "fail_study_plan"

NODE_DISPLAY_NAMES = {
    NODE_LOAD_PROFILE_CONTEXT: "读取画像上下文",
    NODE_BUILD_STUDY_PLAN: "生成学习计划",
    NODE_FAIL_STUDY_PLAN: "记录学习计划失败",
}

NODE_TRACE_DETAILS: dict[str, dict[str, Any]] = {
    NODE_LOAD_PROFILE_CONTEXT: {
        "description": "读取课程画像和用户画像，作为主动学习计划的输入；不写 DB。",
        "reads": ["course", "user", "user_knowledge_state", "exam history", "chat_session", "chat_message"],
        "writes": ["course_profile", "user_profile"],
        "emits": [],
        "input_keys": ["course_id", "user_id"],
        "output_keys": ["course_profile", "user_profile", "load_profile_context_ms", "error"],
    },
    NODE_BUILD_STUDY_PLAN: {
        "description": "把复习、练习和伴读建议压成 3 步可执行学习计划；不调用 Digest Planner。",
        "reads": ["course_profile", "user_profile"],
        "writes": ["study_plan"],
        "emits": [],
        "input_keys": ["course_profile", "user_profile"],
        "output_keys": ["study_plan", "build_study_plan_ms", "error"],
    },
    NODE_FAIL_STUDY_PLAN: {
        "description": "学习计划失败收口节点，保留 state.error 供调用方和 LangSmith 定位。",
        "reads": ["error"],
        "writes": ["error"],
        "emits": [],
        "input_keys": ["error", "course_id", "user_id"],
        "output_keys": ["error"],
    },
}

NODE_TIMING_FIELDS = {
    NODE_LOAD_PROFILE_CONTEXT: "load_profile_context_ms",
    NODE_BUILD_STUDY_PLAN: "build_study_plan_ms",
}

NODE_TRACER = ProfileNodeTracer(
    display_names=NODE_DISPLAY_NAMES,
    trace_details=NODE_TRACE_DETAILS,
    timing_fields=NODE_TIMING_FIELDS,
)


def build_profile_study_plan_graph(
    *,
    context: WorkflowContext | None = None,
    session: Session | None = None,
) -> StateGraph:
    """Build the Profile study-plan graph."""

    resolved_context = context or profile_dev_context(f"{PROFILE_STUDY_PLAN_WORKFLOW_NAME}.langgraph_dev")
    workflow = StateGraph(ProfileStudyPlanState)
    trace = workflow_tracer(context=resolved_context, lane="study_plan")
    workflow.add_node(
        NODE_LOAD_PROFILE_CONTEXT,
        NODE_TRACER.wrap(
            trace,
            NODE_LOAD_PROFILE_CONTEXT,
            build_load_profile_context_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_LOAD_PROFILE_CONTEXT),
    )
    workflow.add_node(
        NODE_BUILD_STUDY_PLAN,
        NODE_TRACER.wrap(
            trace,
            NODE_BUILD_STUDY_PLAN,
            build_study_plan_node(),
        ),
        metadata=NODE_TRACER.metadata(NODE_BUILD_STUDY_PLAN),
    )
    workflow.add_node(
        NODE_FAIL_STUDY_PLAN,
        NODE_TRACER.wrap(
            trace,
            NODE_FAIL_STUDY_PLAN,
            fail_study_plan_node,
        ),
        metadata=NODE_TRACER.metadata(NODE_FAIL_STUDY_PLAN),
    )

    workflow.set_entry_point(NODE_LOAD_PROFILE_CONTEXT)
    workflow.add_conditional_edges(
        NODE_LOAD_PROFILE_CONTEXT,
        route_after_error,
        {"continue": NODE_BUILD_STUDY_PLAN, "fail": NODE_FAIL_STUDY_PLAN},
    )
    workflow.add_conditional_edges(
        NODE_BUILD_STUDY_PLAN,
        route_after_error,
        {"continue": END, "fail": NODE_FAIL_STUDY_PLAN},
    )
    workflow.add_edge(NODE_FAIL_STUDY_PLAN, END)
    return workflow


def create_profile_study_plan_initial_state(
    *,
    course_id: str,
    user_id: str,
) -> ProfileStudyPlanState:
    """Create initial state for the Profile study-plan graph."""

    return {
        "course_id": course_id,
        "user_id": user_id,
        "course_profile": None,
        "user_profile": None,
        "study_plan": [],
        "error": None,
    }


def get_langgraph_dev_profile_study_plan_graph() -> StateGraph:
    """Return a dev graph for LangGraph Studio / diagram export."""

    return build_profile_study_plan_graph(
        context=profile_dev_context(f"{PROFILE_STUDY_PLAN_WORKFLOW_NAME}.langgraph_dev")
    )


async def run_profile_study_plan_workflow(
    *,
    course_id: str,
    user_id: str,
    trigger: str = "profile_study_plan",
    session: Session | None = None,
) -> WorkflowResult[ProfileStudyPlanState]:
    """Run the Profile study-plan lane with one LangSmith root trace."""

    context = WorkflowContext(
        workflow_name=PROFILE_STUDY_PLAN_WORKFLOW_NAME,
        course_id=course_id,
        metadata={
            "build_session_id": f"profile_study_plan:{course_id}:{user_id}",
            "lane": "study_plan",
            "langsmith_run_name": "profile.study_plan.generate",
            "profile_trigger": trigger,
            "user_id": user_id,
        },
    )
    initial_state = create_profile_study_plan_initial_state(
        course_id=course_id,
        user_id=user_id,
    )
    return await run_state_graph(
        workflow_name=PROFILE_STUDY_PLAN_WORKFLOW_NAME,
        graph_builder=lambda: build_profile_study_plan_graph(context=context, session=session),
        initial_state=initial_state,
        context=context,
    )


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="profile_study_plan",
        title="Profile Study Plan Workflow",
        description=(
            "Generate a short actionable study plan from Profile signals. "
            "This does not replace digest/planner."
        ),
        build_graph=get_langgraph_dev_profile_study_plan_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "PROFILE_STUDY_PLAN_WORKFLOW_NAME",
    "ProfileStudyPlanState",
    "WORKFLOW_EXPORTS",
    "build_profile_study_plan_graph",
    "create_profile_study_plan_initial_state",
    "get_langgraph_dev_profile_study_plan_graph",
    "run_profile_study_plan_workflow",
]
