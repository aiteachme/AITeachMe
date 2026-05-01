"""LangGraph definitions for the profile workflow package."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.models import ExamPaper
from app.shared.infra.database import managed_session
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.profile.pipeline.lib.mastery import MasteryUpdateResult, update_mastery_from_exam
from app.workflows.profile.pipeline.lib.reviews import schedule_reviews
from app.workflows.profile.pipeline.lib.course_profile import refresh_course_profile_summary
from app.workflows.profile.pipeline.lib.user_profile import refresh_user_profile_summary
from app.workflows.profile.pipeline.lib.weakness import WeaknessItem, analyze_weakness
from app.workflows.profile.pipeline.prompts import PROMPTS
from app.workflows.profile.pipeline.state import ProfileWorkflowState


def _mastery_updated_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    return {**state, "mastery_updated": True}


def _review_scheduled_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    return {**state, "review_scheduled": True}


def _weaknesses_ranked_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    return {**state, "weaknesses_ranked": True}


def _report_generated_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    return {**state, "report_generated": True}


def build_profile_workflow_graph() -> StateGraph:
    """Build a high-level overview graph for the profile domain."""

    workflow = StateGraph(ProfileWorkflowState)
    workflow.add_node("mastery_updated", _mastery_updated_node)
    workflow.add_node("review_scheduled", _review_scheduled_node)
    workflow.add_node("weaknesses_ranked", _weaknesses_ranked_node)
    workflow.add_node("report_generated", _report_generated_node)
    workflow.set_entry_point("mastery_updated")
    workflow.add_edge("mastery_updated", "review_scheduled")
    workflow.add_edge("review_scheduled", "weaknesses_ranked")
    workflow.add_edge("weaknesses_ranked", "report_generated")
    workflow.add_edge("report_generated", END)
    return workflow


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


def _serialize_mastery_result(result: MasteryUpdateResult) -> dict[str, object]:
    return {
        "exam_paper_id": result.exam_paper_id,
        "states_updated": result.states_updated,
        "updated_state_ids": result.updated_state_ids,
        "already_consumed": result.already_consumed,
    }


def _serialize_weaknesses(items: list[WeaknessItem]) -> list[dict[str, object]]:
    return [
        {
            "knowledge_unit_id": item.knowledge_unit_id,
            "priority": item.priority,
            "reason": item.reason,
            "mastery_score": item.mastery_score,
            "recent_wrong_rate": item.recent_wrong_rate,
            "exam_weight": item.exam_weight,
        }
        for item in items
    ]


def _route_after_step(state: ProfileWorkflowState) -> str:
    return "fail" if state.get("error") else "continue"


NODE_RESOLVE_PROFILE_CONTEXT = "resolve_profile_context"
NODE_UPDATE_MASTERY = "update_mastery"
NODE_SCHEDULE_REVIEWS = "schedule_reviews"
NODE_ANALYZE_WEAKNESS = "analyze_weakness"
NODE_REFRESH_COURSE_PROFILE = "refresh_course_profile"
NODE_REFRESH_USER_PROFILE = "refresh_user_profile"
NODE_FAIL_PROFILE_PIPELINE = "fail_profile_pipeline"

NODE_DISPLAY_NAMES = {
    NODE_RESOLVE_PROFILE_CONTEXT: "解析画像上下文",
    NODE_UPDATE_MASTERY: "更新知识点掌握度",
    NODE_SCHEDULE_REVIEWS: "安排复习任务",
    NODE_ANALYZE_WEAKNESS: "分析薄弱知识点",
    NODE_REFRESH_COURSE_PROFILE: "刷新课程画像",
    NODE_REFRESH_USER_PROFILE: "刷新用户画像",
    NODE_FAIL_PROFILE_PIPELINE: "记录画像失败",
}

NODE_TRACE_DETAILS: dict[str, dict[str, object]] = {
    NODE_RESOLVE_PROFILE_CONTEXT: {
        "description": "读取已评分 ExamPaper，校验课程与用户归属，并把 course_id/user_id 放入画像流水线 state。",
        "reads": ["exam_paper"],
        "writes": ["course_id", "user_id", "error"],
        "input_keys": ["exam_paper_id", "course_id", "user_id"],
        "output_keys": ["course_id", "user_id", "error"],
    },
    NODE_UPDATE_MASTERY: {
        "description": "根据试卷结果更新 user_knowledge_state，记录本轮改动的状态 id，供复习任务和薄弱点分析继续消费。",
        "reads": ["exam_paper", "exam_paper_item", "user_knowledge_state"],
        "writes": ["user_knowledge_state", "mastery_result", "updated_state_ids"],
        "input_keys": ["exam_paper_id"],
        "output_keys": ["mastery_result", "updated_state_ids", "mastery_updated", "error"],
    },
    NODE_SCHEDULE_REVIEWS: {
        "description": "基于本轮更新的掌握度状态安排复习任务；这里只生成复习计划，不改写题目或判卷结果。",
        "reads": ["user_knowledge_state", "updated_state_ids"],
        "writes": ["review_task_ids", "review_scheduled"],
        "input_keys": ["course_id", "user_id", "updated_state_ids"],
        "output_keys": ["review_task_ids", "review_scheduled", "error"],
    },
    NODE_ANALYZE_WEAKNESS: {
        "description": "综合掌握度、近期错题率和考试权重排序薄弱知识点，输出前端和 Interact 可读取的弱项列表。",
        "reads": ["user_knowledge_state", "exam history", "knowledge_unit"],
        "writes": ["weaknesses", "weaknesses_ranked"],
        "input_keys": ["course_id", "user_id", "top_n"],
        "output_keys": ["weaknesses", "weaknesses_ranked", "error"],
    },
    NODE_REFRESH_COURSE_PROFILE: {
        "description": "刷新课程维度画像摘要，供课程页和后续学习建议读取；不在这里生成题目或对话回复。",
        "reads": ["course", "knowledge_unit", "user_knowledge_state"],
        "writes": ["course_profile"],
        "input_keys": ["course_id"],
        "output_keys": ["course_profile", "error"],
    },
    NODE_REFRESH_USER_PROFILE: {
        "description": "刷新用户维度画像摘要，把掌握度、弱项和复习状态收口成可展示报告。",
        "reads": ["user_knowledge_state", "review tasks", "weaknesses"],
        "writes": ["user_profile", "report_generated"],
        "input_keys": ["user_id"],
        "output_keys": ["user_profile", "report_generated", "error"],
    },
    NODE_FAIL_PROFILE_PIPELINE: {
        "description": "画像流水线失败收口节点，保留 state.error 供调用方和 LangSmith 定位。",
        "reads": ["error"],
        "writes": ["error"],
        "input_keys": ["error", "course_id", "user_id", "exam_paper_id"],
        "output_keys": ["error"],
    },
}


def _langgraph_node_metadata(node_key: str) -> dict[str, object]:
    details = NODE_TRACE_DETAILS[node_key]
    return {
        "node_key": node_key,
        "node_display_name": NODE_DISPLAY_NAMES[node_key],
        "node_description": details["description"],
        "reads": list(details["reads"]),
        "writes": list(details["writes"]),
        "state_inputs": list(details["input_keys"]),
        "state_outputs": list(details["output_keys"]),
    }


def _trace_profile_node(trace, node_key: str, handler):
    details = NODE_TRACE_DETAILS[node_key]
    return trace.node(
        handler,
        name=node_key,
        display_name=NODE_DISPLAY_NAMES[node_key],
        description=str(details["description"]),
        input_keys=list(details["input_keys"]),
        output_keys=list(details["output_keys"]),
        metadata=_langgraph_node_metadata(node_key),
    )


def _resolve_profile_context_node(*, session: Session | None = None):
    def resolve_profile_context(state: ProfileWorkflowState) -> ProfileWorkflowState:
        try:
            with _node_session(session) as db_session:
                paper = db_session.get(ExamPaper, state["exam_paper_id"])
                if paper is None:
                    return {
                        **state,
                        "error": f"exam_paper_not_found:{state['exam_paper_id']}",
                    }

                requested_course = state.get("course_id")
                if requested_course and requested_course != paper.course_id:
                    return {
                        **state,
                        "error": f"exam_paper_course_mismatch:{requested_course}!={paper.course_id}",
                    }

                requested_user_id = state.get("user_id")
                if requested_user_id and requested_user_id != paper.user_id:
                    return {
                        **state,
                        "error": f"exam_paper_user_mismatch:{requested_user_id}!={paper.user_id}",
                    }

                return {
                    **state,
                    "course_id": paper.course_id,
                    "user_id": paper.user_id,
                    "error": None,
                }
        except Exception as exc:
            return {
                **state,
                "error": f"resolve_profile_context_failed:{exc}",
            }

    return resolve_profile_context


def _update_mastery_node(*, session: Session | None = None):
    def update_mastery_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        try:
            with _node_session(session) as db_session:
                result = update_mastery_from_exam(
                    db_session,
                    state["exam_paper_id"],
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"update_mastery_failed:{exc}",
            }
        return {
            **state,
            "mastery_result": _serialize_mastery_result(result),
            "updated_state_ids": list(result.updated_state_ids),
            "mastery_updated": True,
            "error": None,
        }

    return update_mastery_node


def _schedule_reviews_node(*, session: Session | None = None):
    def schedule_reviews_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        user_id = state.get("user_id")
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with _node_session(session) as db_session:
                review_tasks = schedule_reviews(
                    db_session,
                    user_id=user_id,
                    course_id=course_id,
                    updated_state_ids=list(state.get("updated_state_ids", [])),
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"schedule_reviews_failed:{exc}",
            }
        return {
            **state,
            "review_task_ids": [int(task.id) for task in review_tasks if task.id is not None],
            "review_scheduled": True,
            "error": None,
        }

    return schedule_reviews_node


def _analyze_weakness_node(*, session: Session | None = None):
    def analyze_weakness_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        user_id = state.get("user_id")
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with _node_session(session) as db_session:
                weaknesses = analyze_weakness(
                    db_session,
                    user_id=user_id,
                    course_id=course_id,
                    top_n=int(state.get("top_n") or 20),
                )
        except Exception as exc:
            return {
                **state,
                "error": f"analyze_weakness_failed:{exc}",
            }
        return {
            **state,
            "weaknesses": _serialize_weaknesses(weaknesses),
            "weaknesses_ranked": True,
            "error": None,
        }

    return analyze_weakness_node


def _refresh_course_profile_node(*, session: Session | None = None):
    def refresh_course_profile_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        if not course_id:
            return {
                **state,
                "error": "profile_course_missing",
            }

        try:
            with _node_session(session) as db_session:
                summary = refresh_course_profile_summary(
                    db_session,
                    course_id=course_id,
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"refresh_course_profile_failed:{exc}",
            }
        return {
            **state,
            "course_profile": summary.model_dump(mode="json"),
            "error": None,
        }

    return refresh_course_profile_node


def _refresh_user_profile_node(*, session: Session | None = None):
    def refresh_user_profile_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        user_id = state.get("user_id")
        if not user_id:
            return {
                **state,
                "error": "profile_user_missing",
            }

        try:
            with _node_session(session) as db_session:
                summary = refresh_user_profile_summary(
                    db_session,
                    user_id=user_id,
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"refresh_user_profile_failed:{exc}",
            }
        return {
            **state,
            "user_profile": summary.model_dump(mode="json"),
            "report_generated": True,
            "error": None,
        }

    return refresh_user_profile_node


def _fail_profile_pipeline_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    return state


def build_profile_pipeline_graph(*, session: Session | None = None) -> StateGraph:
    """Build an executable profile pipeline graph for local debugging."""

    workflow = StateGraph(ProfileWorkflowState)
    trace = workflow_tracer(workflow="profile.pipeline", lane="profile")
    workflow.add_node(
        NODE_RESOLVE_PROFILE_CONTEXT,
        _trace_profile_node(
            trace,
            NODE_RESOLVE_PROFILE_CONTEXT,
            _resolve_profile_context_node(session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_RESOLVE_PROFILE_CONTEXT),
    )
    workflow.add_node(
        NODE_UPDATE_MASTERY,
        _trace_profile_node(
            trace,
            NODE_UPDATE_MASTERY,
            _update_mastery_node(session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_UPDATE_MASTERY),
    )
    workflow.add_node(
        NODE_SCHEDULE_REVIEWS,
        _trace_profile_node(
            trace,
            NODE_SCHEDULE_REVIEWS,
            _schedule_reviews_node(session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_SCHEDULE_REVIEWS),
    )
    workflow.add_node(
        NODE_ANALYZE_WEAKNESS,
        _trace_profile_node(
            trace,
            NODE_ANALYZE_WEAKNESS,
            _analyze_weakness_node(session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_ANALYZE_WEAKNESS),
    )
    workflow.add_node(
        NODE_REFRESH_COURSE_PROFILE,
        _trace_profile_node(
            trace,
            NODE_REFRESH_COURSE_PROFILE,
            _refresh_course_profile_node(session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_REFRESH_COURSE_PROFILE),
    )
    workflow.add_node(
        NODE_REFRESH_USER_PROFILE,
        _trace_profile_node(
            trace,
            NODE_REFRESH_USER_PROFILE,
            _refresh_user_profile_node(session=session),
        ),
        metadata=_langgraph_node_metadata(NODE_REFRESH_USER_PROFILE),
    )
    workflow.add_node(
        NODE_FAIL_PROFILE_PIPELINE,
        _trace_profile_node(
            trace,
            NODE_FAIL_PROFILE_PIPELINE,
            _fail_profile_pipeline_node,
        ),
        metadata=_langgraph_node_metadata(NODE_FAIL_PROFILE_PIPELINE),
    )

    workflow.set_entry_point(NODE_RESOLVE_PROFILE_CONTEXT)
    workflow.add_conditional_edges(
        NODE_RESOLVE_PROFILE_CONTEXT,
        _route_after_step,
        {"continue": NODE_UPDATE_MASTERY, "fail": NODE_FAIL_PROFILE_PIPELINE},
    )
    workflow.add_conditional_edges(
        NODE_UPDATE_MASTERY,
        _route_after_step,
        {"continue": NODE_SCHEDULE_REVIEWS, "fail": NODE_FAIL_PROFILE_PIPELINE},
    )
    workflow.add_conditional_edges(
        NODE_SCHEDULE_REVIEWS,
        _route_after_step,
        {"continue": NODE_ANALYZE_WEAKNESS, "fail": NODE_FAIL_PROFILE_PIPELINE},
    )
    workflow.add_conditional_edges(
        NODE_ANALYZE_WEAKNESS,
        _route_after_step,
        {"continue": NODE_REFRESH_COURSE_PROFILE, "fail": NODE_FAIL_PROFILE_PIPELINE},
    )
    workflow.add_conditional_edges(
        NODE_REFRESH_COURSE_PROFILE,
        _route_after_step,
        {"continue": NODE_REFRESH_USER_PROFILE, "fail": NODE_FAIL_PROFILE_PIPELINE},
    )
    workflow.add_edge(NODE_REFRESH_USER_PROFILE, END)
    workflow.add_edge(NODE_FAIL_PROFILE_PIPELINE, END)
    return workflow


def create_profile_initial_state(
    *,
    exam_paper_id: int,
    course_id: str | None = None,
    user_id: str | None = None,
    top_n: int = 20,
) -> ProfileWorkflowState:
    """Create initial state for the executable profile pipeline."""

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


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="profile_pipeline",
        title="Profile Pipeline Workflow",
        description="Executable profile pipeline from mastery updates to review scheduling, weakness analysis, and profile refresh.",
        build_graph=build_profile_pipeline_graph,
        prompts=PROMPTS,
    ),
    WorkflowGraphExport(
        key="profile_flow",
        title="Profile Workflow",
        description="High-level profile workflow from mastery updates to review scheduling, weakness ranking, and report suggestions.",
        build_graph=build_profile_workflow_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "ProfileWorkflowState",
    "WORKFLOW_EXPORTS",
    "build_profile_pipeline_graph",
    "build_profile_workflow_graph",
    "create_profile_initial_state",
]
