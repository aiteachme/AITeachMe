"""Profile snapshot graph definition and runtime entrypoint.

This lane serves Profile page reads. It builds current mastery/profile
snapshots without mutating the database or scheduling reviews.
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
from app.workflows.profile.pipeline.nodes import (
    build_course_profile_snapshot_node,
    build_load_mastery_overview_node,
    build_user_profile_snapshot_node,
    build_validate_profile_snapshot_context_node,
    fail_profile_pipeline_node,
)
from app.workflows.profile.pipeline.prompts import PROMPTS
from app.workflows.profile.snapshot.state import ProfileSnapshotState

PROFILE_SNAPSHOT_WORKFLOW_NAME = "profile.snapshot"

NODE_VALIDATE_SNAPSHOT_CONTEXT = "validate_snapshot_context"
NODE_LOAD_MASTERY_OVERVIEW = "load_mastery_overview"
NODE_BUILD_COURSE_PROFILE = "build_course_profile"
NODE_BUILD_USER_PROFILE = "build_user_profile"
NODE_FAIL_PROFILE_SNAPSHOT = "fail_profile_snapshot"

NODE_DISPLAY_NAMES = {
    NODE_VALIDATE_SNAPSHOT_CONTEXT: "校验画像快照上下文",
    NODE_LOAD_MASTERY_OVERVIEW: "读取掌握度概览",
    NODE_BUILD_COURSE_PROFILE: "生成课程画像快照",
    NODE_BUILD_USER_PROFILE: "生成用户画像快照",
    NODE_FAIL_PROFILE_SNAPSHOT: "记录画像快照失败",
}

NODE_TRACE_DETAILS: dict[str, dict[str, Any]] = {
    NODE_VALIDATE_SNAPSHOT_CONTEXT: {
        "description": "校验 Profile 页只读快照请求的 course_id/user_id 是否匹配，避免跨用户读取画像。",
        "reads": ["course"],
        "writes": ["course_id", "user_id", "error"],
        "emits": [],
        "input_keys": ["course_id", "user_id"],
        "output_keys": ["course_id", "user_id", "validate_snapshot_ms", "error"],
    },
    NODE_LOAD_MASTERY_OVERVIEW: {
        "description": "读取知识点掌握度列表和知识点展示名，生成 Profile 页掌握度概览 payload。",
        "reads": ["user_knowledge_state", "knowledge_unit"],
        "writes": ["knowledge_unit_states", "weak_knowledge_unit_count"],
        "emits": [],
        "input_keys": ["course_id", "user_id"],
        "output_keys": ["knowledge_unit_states", "weak_knowledge_unit_count", "load_mastery_overview_ms", "error"],
    },
    NODE_BUILD_COURSE_PROFILE: {
        "description": "只读生成课程画像快照，包含推荐题型、练习模式、难度聚焦、复习数量和对话偏好信号。",
        "reads": ["course", "exam history", "user_knowledge_state", "chat_session", "chat_message"],
        "writes": ["course_profile"],
        "emits": [],
        "input_keys": ["course_id", "user_id"],
        "output_keys": ["course_profile", "build_course_profile_ms", "error"],
    },
    NODE_BUILD_USER_PROFILE: {
        "description": "只读生成用户画像快照，包含跨课程偏好、练习节奏、持续性和对话记忆信号。",
        "reads": ["user", "course", "exam history", "user_knowledge_state", "chat_session", "chat_message"],
        "writes": ["user_profile", "report_generated"],
        "emits": [],
        "input_keys": ["user_id"],
        "output_keys": ["user_profile", "report_generated", "build_user_profile_ms", "error"],
    },
    NODE_FAIL_PROFILE_SNAPSHOT: {
        "description": "画像快照失败收口节点，保留 state.error 供调用方和 LangSmith 定位。",
        "reads": ["error"],
        "writes": ["error"],
        "emits": [],
        "input_keys": ["error", "course_id", "user_id"],
        "output_keys": ["error"],
    },
}

NODE_TIMING_FIELDS = {
    NODE_VALIDATE_SNAPSHOT_CONTEXT: "validate_snapshot_ms",
    NODE_LOAD_MASTERY_OVERVIEW: "load_mastery_overview_ms",
    NODE_BUILD_COURSE_PROFILE: "build_course_profile_ms",
    NODE_BUILD_USER_PROFILE: "build_user_profile_ms",
}

NODE_TRACER = ProfileNodeTracer(
    display_names=NODE_DISPLAY_NAMES,
    trace_details=NODE_TRACE_DETAILS,
    timing_fields=NODE_TIMING_FIELDS,
)


def build_profile_snapshot_graph(
    *,
    context: WorkflowContext | None = None,
    session: Session | None = None,
) -> StateGraph:
    """Build the read-only Profile snapshot graph used by Profile pages."""

    resolved_context = context or profile_dev_context(f"{PROFILE_SNAPSHOT_WORKFLOW_NAME}.langgraph_dev")
    workflow = StateGraph(ProfileSnapshotState)
    trace = workflow_tracer(context=resolved_context, lane="snapshot")
    workflow.add_node(
        NODE_VALIDATE_SNAPSHOT_CONTEXT,
        NODE_TRACER.wrap(
            trace,
            NODE_VALIDATE_SNAPSHOT_CONTEXT,
            build_validate_profile_snapshot_context_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_VALIDATE_SNAPSHOT_CONTEXT),
    )
    workflow.add_node(
        NODE_LOAD_MASTERY_OVERVIEW,
        NODE_TRACER.wrap(
            trace,
            NODE_LOAD_MASTERY_OVERVIEW,
            build_load_mastery_overview_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_LOAD_MASTERY_OVERVIEW),
    )
    workflow.add_node(
        NODE_BUILD_COURSE_PROFILE,
        NODE_TRACER.wrap(
            trace,
            NODE_BUILD_COURSE_PROFILE,
            build_course_profile_snapshot_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_BUILD_COURSE_PROFILE),
    )
    workflow.add_node(
        NODE_BUILD_USER_PROFILE,
        NODE_TRACER.wrap(
            trace,
            NODE_BUILD_USER_PROFILE,
            build_user_profile_snapshot_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_BUILD_USER_PROFILE),
    )
    workflow.add_node(
        NODE_FAIL_PROFILE_SNAPSHOT,
        NODE_TRACER.wrap(
            trace,
            NODE_FAIL_PROFILE_SNAPSHOT,
            fail_profile_pipeline_node,
        ),
        metadata=NODE_TRACER.metadata(NODE_FAIL_PROFILE_SNAPSHOT),
    )

    workflow.set_entry_point(NODE_VALIDATE_SNAPSHOT_CONTEXT)
    workflow.add_conditional_edges(
        NODE_VALIDATE_SNAPSHOT_CONTEXT,
        route_after_error,
        {"continue": NODE_LOAD_MASTERY_OVERVIEW, "fail": NODE_FAIL_PROFILE_SNAPSHOT},
    )
    workflow.add_conditional_edges(
        NODE_LOAD_MASTERY_OVERVIEW,
        route_after_error,
        {"continue": NODE_BUILD_COURSE_PROFILE, "fail": NODE_FAIL_PROFILE_SNAPSHOT},
    )
    workflow.add_conditional_edges(
        NODE_BUILD_COURSE_PROFILE,
        route_after_error,
        {"continue": NODE_BUILD_USER_PROFILE, "fail": NODE_FAIL_PROFILE_SNAPSHOT},
    )
    workflow.add_edge(NODE_BUILD_USER_PROFILE, END)
    workflow.add_edge(NODE_FAIL_PROFILE_SNAPSHOT, END)
    return workflow


def create_profile_snapshot_initial_state(
    *,
    course_id: str,
    user_id: str,
    top_n: int = 20,
) -> ProfileSnapshotState:
    """Create initial state for the read-only Profile snapshot graph."""

    return {
        "course_id": course_id,
        "user_id": user_id,
        "top_n": top_n,
        "knowledge_unit_states": [],
        "weak_knowledge_unit_count": 0,
        "course_profile": None,
        "user_profile": None,
        "report_generated": False,
        "error": None,
    }


def get_langgraph_dev_profile_snapshot_graph() -> StateGraph:
    """Return a read-only dev graph for LangGraph Studio / diagram export."""

    return build_profile_snapshot_graph(
        context=profile_dev_context(f"{PROFILE_SNAPSHOT_WORKFLOW_NAME}.langgraph_dev")
    )


async def run_profile_snapshot_workflow(
    *,
    course_id: str,
    user_id: str,
    top_n: int = 20,
    trigger: str = "profile_mastery_overview",
    session: Session | None = None,
) -> WorkflowResult[ProfileSnapshotState]:
    """Run the read-only Profile snapshot graph with one LangSmith root trace."""

    context = WorkflowContext(
        workflow_name=PROFILE_SNAPSHOT_WORKFLOW_NAME,
        course_id=course_id,
        metadata={
            "build_session_id": f"profile_snapshot:{course_id}:{user_id}",
            "lane": "snapshot",
            "langsmith_run_name": "profile.snapshot.mastery_overview",
            "profile_trigger": trigger,
            "user_id": user_id,
        },
    )
    initial_state = create_profile_snapshot_initial_state(
        course_id=course_id,
        user_id=user_id,
        top_n=top_n,
    )
    return await run_state_graph(
        workflow_name=PROFILE_SNAPSHOT_WORKFLOW_NAME,
        graph_builder=lambda: build_profile_snapshot_graph(context=context, session=session),
        initial_state=initial_state,
        context=context,
    )


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="profile_snapshot",
        title="Profile Snapshot Workflow",
        description=(
            "Read-only profile snapshot for Profile pages: context validation, "
            "mastery overview, course profile, and user profile."
        ),
        build_graph=get_langgraph_dev_profile_snapshot_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "PROFILE_SNAPSHOT_WORKFLOW_NAME",
    "ProfileSnapshotState",
    "WORKFLOW_EXPORTS",
    "build_profile_snapshot_graph",
    "create_profile_snapshot_initial_state",
    "get_langgraph_dev_profile_snapshot_graph",
    "run_profile_snapshot_workflow",
]
