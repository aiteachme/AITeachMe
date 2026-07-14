"""Profile update graph definition and runtime entrypoint.

This lane is triggered after exam grading. It mutates mastery/review/profile
tables through lib helpers, and keeps API scheduling outside the graph.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.shared.infra.database import get_session
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.shared.infra.workflow.result import WorkflowResult
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.profile.common import ProfileNodeTracer, profile_dev_context, route_after_error
from app.workflows.profile.common.nodes import (
    build_analyze_weakness_node,
    build_refresh_course_profile_node,
    build_refresh_user_profile_node,
    build_resolve_exam_profile_context_node,
    build_schedule_reviews_node,
    build_update_mastery_node,
    fail_profile_lane_node,
)
from app.workflows.profile.common.prompts import PROMPTS
from app.workflows.profile.update.state import ProfileUpdateState

PROFILE_UPDATE_WORKFLOW_NAME = "profile.update"

NODE_RESOLVE_PROFILE_CONTEXT = "resolve_profile_context"
NODE_UPDATE_MASTERY = "update_mastery"
NODE_SCHEDULE_REVIEWS = "schedule_reviews"
NODE_ANALYZE_WEAKNESS = "analyze_weakness"
NODE_REFRESH_COURSE_PROFILE = "refresh_course_profile"
NODE_REFRESH_USER_PROFILE = "refresh_user_profile"
NODE_FAIL_PROFILE_UPDATE = "fail_profile_update"

NODE_DISPLAY_NAMES = {
    NODE_RESOLVE_PROFILE_CONTEXT: "解析画像上下文",
    NODE_UPDATE_MASTERY: "更新知识点掌握度",
    NODE_SCHEDULE_REVIEWS: "安排复习任务",
    NODE_ANALYZE_WEAKNESS: "分析薄弱知识点",
    NODE_REFRESH_COURSE_PROFILE: "刷新课程画像",
    NODE_REFRESH_USER_PROFILE: "刷新用户画像",
    NODE_FAIL_PROFILE_UPDATE: "记录画像更新失败",
}

NODE_TRACE_DETAILS: dict[str, dict[str, Any]] = {
    NODE_RESOLVE_PROFILE_CONTEXT: {
        "description": "读取已评分 ExamPaper，校验课程与用户归属，并把 course_id/user_id 放入画像更新 state。",
        "reads": ["exam_paper"],
        "writes": ["course_id", "user_id", "error"],
        "emits": [],
        "input_keys": ["exam_paper_id", "course_id", "user_id"],
        "output_keys": ["course_id", "user_id", "resolve_context_ms", "error"],
    },
    NODE_UPDATE_MASTERY: {
        "description": "根据试卷结果更新 user_knowledge_state，记录本轮改动的状态 id，供复习任务和薄弱点分析继续消费。",
        "reads": ["exam_paper", "exam_paper_item", "user_knowledge_state"],
        "writes": ["user_knowledge_state", "mastery_result", "updated_state_ids"],
        "emits": [],
        "input_keys": ["exam_paper_id"],
        "output_keys": ["mastery_result", "updated_state_ids", "mastery_updated", "update_mastery_ms", "error"],
    },
    NODE_SCHEDULE_REVIEWS: {
        "description": "基于本轮更新的掌握度状态安排复习任务；这里只生成复习计划，不改写题目或判卷结果。",
        "reads": ["user_knowledge_state", "updated_state_ids"],
        "writes": ["review_task_ids", "review_scheduled"],
        "emits": [],
        "input_keys": ["course_id", "user_id", "updated_state_ids"],
        "output_keys": ["review_task_ids", "review_scheduled", "schedule_reviews_ms", "error"],
    },
    NODE_ANALYZE_WEAKNESS: {
        "description": "综合掌握度、近期错题率和考试权重排序薄弱知识点，输出前端和 Interact 可读取的弱项列表。",
        "reads": ["user_knowledge_state", "exam history", "knowledge_unit"],
        "writes": ["weaknesses", "weaknesses_ranked"],
        "emits": [],
        "input_keys": ["course_id", "user_id", "top_n"],
        "output_keys": ["weaknesses", "weaknesses_ranked", "analyze_weakness_ms", "error"],
    },
    NODE_REFRESH_COURSE_PROFILE: {
        "description": "刷新并持久化课程维度画像摘要，供课程页和后续学习建议读取；不在这里生成题目或对话回复。",
        "reads": ["course", "knowledge_unit", "user_knowledge_state", "chat_session", "chat_message"],
        "writes": ["course.profile_json", "course_profile"],
        "emits": [],
        "input_keys": ["course_id"],
        "output_keys": ["course_profile", "refresh_course_profile_ms", "error"],
    },
    NODE_REFRESH_USER_PROFILE: {
        "description": "刷新并持久化用户维度画像摘要，把掌握度、弱项、复习状态和对话偏好收口成可展示报告。",
        "reads": ["user", "course", "user_knowledge_state", "review tasks", "chat_session", "chat_message"],
        "writes": ["user.profile_json", "user_profile", "report_generated"],
        "emits": [],
        "input_keys": ["user_id"],
        "output_keys": ["user_profile", "report_generated", "refresh_user_profile_ms", "error"],
    },
    NODE_FAIL_PROFILE_UPDATE: {
        "description": "画像更新失败收口节点，保留 state.error 供调用方和 LangSmith 定位。",
        "reads": ["error"],
        "writes": ["error"],
        "emits": [],
        "input_keys": ["error", "course_id", "user_id", "exam_paper_id"],
        "output_keys": ["error"],
    },
}

NODE_TIMING_FIELDS = {
    NODE_RESOLVE_PROFILE_CONTEXT: "resolve_context_ms",
    NODE_UPDATE_MASTERY: "update_mastery_ms",
    NODE_SCHEDULE_REVIEWS: "schedule_reviews_ms",
    NODE_ANALYZE_WEAKNESS: "analyze_weakness_ms",
    NODE_REFRESH_COURSE_PROFILE: "refresh_course_profile_ms",
    NODE_REFRESH_USER_PROFILE: "refresh_user_profile_ms",
}

NODE_TRACER = ProfileNodeTracer(
    display_names=NODE_DISPLAY_NAMES,
    trace_details=NODE_TRACE_DETAILS,
    timing_fields=NODE_TIMING_FIELDS,
)


def build_profile_update_graph(
    *,
    context: WorkflowContext | None = None,
    session: Session | None = None,
) -> StateGraph:
    """Build the executable exam-driven Profile update graph."""

    resolved_context = context or profile_dev_context(f"{PROFILE_UPDATE_WORKFLOW_NAME}.langgraph_dev")
    workflow = StateGraph(ProfileUpdateState)
    trace = workflow_tracer(context=resolved_context, lane="update")
    workflow.add_node(
        NODE_RESOLVE_PROFILE_CONTEXT,
        NODE_TRACER.wrap(
            trace,
            NODE_RESOLVE_PROFILE_CONTEXT,
            build_resolve_exam_profile_context_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_RESOLVE_PROFILE_CONTEXT),
    )
    workflow.add_node(
        NODE_UPDATE_MASTERY,
        NODE_TRACER.wrap(
            trace,
            NODE_UPDATE_MASTERY,
            build_update_mastery_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_UPDATE_MASTERY),
    )
    workflow.add_node(
        NODE_SCHEDULE_REVIEWS,
        NODE_TRACER.wrap(
            trace,
            NODE_SCHEDULE_REVIEWS,
            build_schedule_reviews_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_SCHEDULE_REVIEWS),
    )
    workflow.add_node(
        NODE_ANALYZE_WEAKNESS,
        NODE_TRACER.wrap(
            trace,
            NODE_ANALYZE_WEAKNESS,
            build_analyze_weakness_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_ANALYZE_WEAKNESS),
    )
    workflow.add_node(
        NODE_REFRESH_COURSE_PROFILE,
        NODE_TRACER.wrap(
            trace,
            NODE_REFRESH_COURSE_PROFILE,
            build_refresh_course_profile_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_REFRESH_COURSE_PROFILE),
    )
    workflow.add_node(
        NODE_REFRESH_USER_PROFILE,
        NODE_TRACER.wrap(
            trace,
            NODE_REFRESH_USER_PROFILE,
            build_refresh_user_profile_node(session=session),
        ),
        metadata=NODE_TRACER.metadata(NODE_REFRESH_USER_PROFILE),
    )
    workflow.add_node(
        NODE_FAIL_PROFILE_UPDATE,
        NODE_TRACER.wrap(
            trace,
            NODE_FAIL_PROFILE_UPDATE,
            fail_profile_lane_node,
        ),
        metadata=NODE_TRACER.metadata(NODE_FAIL_PROFILE_UPDATE),
    )

    workflow.set_entry_point(NODE_RESOLVE_PROFILE_CONTEXT)
    workflow.add_conditional_edges(
        NODE_RESOLVE_PROFILE_CONTEXT,
        route_after_error,
        {"continue": NODE_UPDATE_MASTERY, "fail": NODE_FAIL_PROFILE_UPDATE},
    )
    workflow.add_conditional_edges(
        NODE_UPDATE_MASTERY,
        route_after_error,
        {"continue": NODE_SCHEDULE_REVIEWS, "fail": NODE_FAIL_PROFILE_UPDATE},
    )
    workflow.add_conditional_edges(
        NODE_SCHEDULE_REVIEWS,
        route_after_error,
        {"continue": NODE_ANALYZE_WEAKNESS, "fail": NODE_FAIL_PROFILE_UPDATE},
    )
    workflow.add_conditional_edges(
        NODE_ANALYZE_WEAKNESS,
        route_after_error,
        {"continue": NODE_REFRESH_COURSE_PROFILE, "fail": NODE_FAIL_PROFILE_UPDATE},
    )
    workflow.add_conditional_edges(
        NODE_REFRESH_COURSE_PROFILE,
        route_after_error,
        {"continue": NODE_REFRESH_USER_PROFILE, "fail": NODE_FAIL_PROFILE_UPDATE},
    )
    workflow.add_edge(NODE_REFRESH_USER_PROFILE, END)
    workflow.add_edge(NODE_FAIL_PROFILE_UPDATE, END)
    return workflow


def create_profile_update_initial_state(
    *,
    exam_paper_id: int,
    course_id: str | None = None,
    user_id: str | None = None,
    top_n: int = 20,
) -> ProfileUpdateState:
    """Create initial state for the exam-driven Profile update graph."""

    return {
        "exam_paper_id": exam_paper_id,
        "course_id": course_id or "",
        "user_id": user_id or "",
        "top_n": top_n,
        "updated_state_ids": [],
        "review_task_ids": [],
        "weaknesses": [],
        "mastery_result": None,
        "course_profile": None,
        "user_profile": None,
        "mastery_updated": False,
        "review_scheduled": False,
        "weaknesses_ranked": False,
        "report_generated": False,
        "error": None,
    }


def get_langgraph_dev_profile_update_graph() -> StateGraph:
    """Return a dev graph for LangGraph Studio / diagram export."""

    return build_profile_update_graph(
        context=profile_dev_context(f"{PROFILE_UPDATE_WORKFLOW_NAME}.langgraph_dev")
    )


async def run_profile_update_workflow(
    *,
    exam_paper_id: int,
    course_id: str | None = None,
    user_id: str | None = None,
    top_n: int = 20,
    trigger: str = "exam_graded",
    session: Session | None = None,
) -> WorkflowResult[ProfileUpdateState]:
    """Run one atomic, user-serialized Profile update.

    When ``session`` is provided, its caller owns commit/rollback and therefore
    also owns the lifetime of the Profile transaction lock acquired here.
    """

    context = WorkflowContext(
        workflow_name=PROFILE_UPDATE_WORKFLOW_NAME,
        course_id=course_id or "",
        metadata={
            "build_session_id": f"profile_exam:{exam_paper_id}",
            "lane": "update",
            "langsmith_run_name": "画像引擎：考后更新画像",
            "profile_trigger": trigger,
            "exam_paper_id": exam_paper_id,
            "user_id": user_id or "",
        },
    )
    initial_state = create_profile_update_initial_state(
        exam_paper_id=exam_paper_id,
        course_id=course_id,
        user_id=user_id,
        top_n=top_n,
    )
    async def _run(workflow_session: Session) -> WorkflowResult[ProfileUpdateState]:
        return await run_state_graph(
            workflow_name=PROFILE_UPDATE_WORKFLOW_NAME,
            graph_builder=lambda: build_profile_update_graph(
                context=context,
                session=workflow_session,
            ),
            initial_state=initial_state,
            context=context,
        )

    if session is not None:
        return await _run(session)

    workflow_session = get_session()
    try:
        result = await _run(workflow_session)
        final_state = result.value if isinstance(result.value, dict) else {}
        if result.failed or final_state.get("error"):
            workflow_session.rollback()
        else:
            workflow_session.commit()
        return result
    except BaseException:
        workflow_session.rollback()
        raise
    finally:
        workflow_session.close()


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="profile_update",
        title="考后画像更新链路",
        description=(
            "测验驱动的画像更新：解析上下文、更新掌握度、安排复习、分析薄弱点并刷新画像摘要。"
        ),
        build_graph=get_langgraph_dev_profile_update_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "PROFILE_UPDATE_WORKFLOW_NAME",
    "ProfileUpdateState",
    "WORKFLOW_EXPORTS",
    "build_profile_update_graph",
    "create_profile_update_initial_state",
    "get_langgraph_dev_profile_update_graph",
    "run_profile_update_workflow",
]
