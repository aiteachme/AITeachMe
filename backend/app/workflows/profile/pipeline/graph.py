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
from app.workflows.profile.pipeline.lib.subject_profile import refresh_subject_profile_summary
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

                requested_subject = state.get("subject_id")
                if requested_subject and requested_subject != paper.subject_id:
                    return {
                        **state,
                        "error": f"exam_paper_subject_mismatch:{requested_subject}!={paper.subject_id}",
                    }

                requested_user_id = state.get("user_id")
                if requested_user_id and requested_user_id != paper.user_id:
                    return {
                        **state,
                        "error": f"exam_paper_user_mismatch:{requested_user_id}!={paper.user_id}",
                    }

                return {
                    **state,
                    "subject_id": paper.subject_id,
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
        subject_id = state.get("subject_id")
        user_id = state.get("user_id")
        if not subject_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with _node_session(session) as db_session:
                review_tasks = schedule_reviews(
                    db_session,
                    user_id=user_id,
                    subject_id=subject_id,
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
        subject_id = state.get("subject_id")
        user_id = state.get("user_id")
        if not subject_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with _node_session(session) as db_session:
                weaknesses = analyze_weakness(
                    db_session,
                    user_id=user_id,
                    subject_id=subject_id,
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


def _refresh_subject_profile_node(*, session: Session | None = None):
    def refresh_subject_profile_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        subject_id = state.get("subject_id")
        if not subject_id:
            return {
                **state,
                "error": "profile_subject_missing",
            }

        try:
            with _node_session(session) as db_session:
                summary = refresh_subject_profile_summary(
                    db_session,
                    subject_id=subject_id,
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"refresh_subject_profile_failed:{exc}",
            }
        return {
            **state,
            "subject_profile": summary.model_dump(mode="json"),
            "error": None,
        }

    return refresh_subject_profile_node


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
        "resolve_profile_context",
        trace.node(
            _resolve_profile_context_node(session=session),
            name="resolve_profile_context",
        ),
    )
    workflow.add_node(
        "update_mastery",
        trace.node(
            _update_mastery_node(session=session),
            name="update_mastery",
        ),
    )
    workflow.add_node(
        "schedule_reviews",
        trace.node(
            _schedule_reviews_node(session=session),
            name="schedule_reviews",
        ),
    )
    workflow.add_node(
        "analyze_weakness",
        trace.node(
            _analyze_weakness_node(session=session),
            name="analyze_weakness",
        ),
    )
    workflow.add_node(
        "refresh_subject_profile",
        trace.node(
            _refresh_subject_profile_node(session=session),
            name="refresh_subject_profile",
        ),
    )
    workflow.add_node(
        "refresh_user_profile",
        trace.node(
            _refresh_user_profile_node(session=session),
            name="refresh_user_profile",
        ),
    )
    workflow.add_node(
        "fail_profile_pipeline",
        trace.node(
            _fail_profile_pipeline_node,
            name="fail_profile_pipeline",
        ),
    )

    workflow.set_entry_point("resolve_profile_context")
    workflow.add_conditional_edges(
        "resolve_profile_context",
        _route_after_step,
        {"continue": "update_mastery", "fail": "fail_profile_pipeline"},
    )
    workflow.add_conditional_edges(
        "update_mastery",
        _route_after_step,
        {"continue": "schedule_reviews", "fail": "fail_profile_pipeline"},
    )
    workflow.add_conditional_edges(
        "schedule_reviews",
        _route_after_step,
        {"continue": "analyze_weakness", "fail": "fail_profile_pipeline"},
    )
    workflow.add_conditional_edges(
        "analyze_weakness",
        _route_after_step,
        {"continue": "refresh_subject_profile", "fail": "fail_profile_pipeline"},
    )
    workflow.add_conditional_edges(
        "refresh_subject_profile",
        _route_after_step,
        {"continue": "refresh_user_profile", "fail": "fail_profile_pipeline"},
    )
    workflow.add_edge("refresh_user_profile", END)
    workflow.add_edge("fail_profile_pipeline", END)
    return workflow

def create_profile_initial_state(
    *,
    exam_paper_id: int,
    subject_id: str | None = None,
    user_id: str | None = None,
    top_n: int = 20,
) -> ProfileWorkflowState:
    """Create initial state for the executable profile pipeline."""

    return {
        "exam_paper_id": exam_paper_id,
        "subject_id": subject_id or "",
        "user_id": user_id or "",
        "top_n": top_n,
        "updated_state_ids": [],
        "review_task_ids": [],
        "weaknesses": [],
        "mastery_result": None,
        "subject_profile": None,
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
