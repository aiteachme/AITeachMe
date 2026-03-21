"""LangGraph definitions for the examine workflow package."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.workflows.examine.exam_grade_workflow import build_exam_grade_graph
from app.workflows.examine.question_build_workflow import build_question_build_graph
from app.workflows.examine.state import ExamineWorkflowState


def _question_templates_ready_node(state: ExamineWorkflowState) -> ExamineWorkflowState:
    return {**state, "question_templates_ready": True}


def _exam_paper_ready_node(state: ExamineWorkflowState) -> ExamineWorkflowState:
    return {**state, "exam_paper_ready": True}


def _exam_graded_node(state: ExamineWorkflowState) -> ExamineWorkflowState:
    return {
        **state,
        "exam_graded": True,
        "mastery_updated": True,
        "review_scheduled": True,
    }


def build_examine_workflow_graph() -> StateGraph:
    """Build a high-level overview graph for the examine domain."""

    workflow = StateGraph(ExamineWorkflowState)
    workflow.add_node("question_templates_ready", _question_templates_ready_node)
    workflow.add_node("exam_paper_ready", _exam_paper_ready_node)
    workflow.add_node("exam_graded", _exam_graded_node)
    workflow.set_entry_point("question_templates_ready")
    workflow.add_edge("question_templates_ready", "exam_paper_ready")
    workflow.add_edge("exam_paper_ready", "exam_graded")
    workflow.add_edge("exam_graded", END)
    return workflow


__all__ = [
    "ExamineWorkflowState",
    "build_examine_workflow_graph",
    "build_exam_grade_graph",
    "build_question_build_graph",
]
