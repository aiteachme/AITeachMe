"""LangGraph definitions for the profile workflow package."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.workflows.profile.state import ProfileWorkflowState


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


__all__ = ["ProfileWorkflowState", "build_profile_workflow_graph"]
