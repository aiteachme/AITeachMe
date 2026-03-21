"""Minimal LangGraph definition for examine workflows."""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from app.workflows.examine.state import ExamineWorkflowState


def _prepare_exam_node(state: ExamineWorkflowState) -> ExamineWorkflowState:
    return {**state, "prepared": True}


def _grade_exam_node(state: ExamineWorkflowState) -> ExamineWorkflowState:
    return {**state, "graded": True}


def build_examine_workflow_graph() -> StateGraph:
    """Build a tiny graph for the examine domain."""

    workflow = StateGraph(ExamineWorkflowState)
    workflow.add_node("prepare_exam", _prepare_exam_node)
    workflow.add_node("grade_submission", _grade_exam_node)
    workflow.set_entry_point("prepare_exam")
    workflow.add_edge("prepare_exam", "grade_submission")
    workflow.add_edge("grade_submission", END)
    return workflow


__all__ = ["ExamineWorkflowState", "build_examine_workflow_graph"]
