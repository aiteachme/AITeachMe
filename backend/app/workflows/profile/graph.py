"""Minimal LangGraph definition for profile workflows."""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from app.workflows.profile.state import ProfileWorkflowState


def _aggregate_profile_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    return {**state, "aggregated": True}


def _generate_report_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
    return {**state, "reported": True}


def build_profile_workflow_graph() -> StateGraph:
    """Build a tiny graph for the profile domain."""

    workflow = StateGraph(ProfileWorkflowState)
    workflow.add_node("aggregate_profile", _aggregate_profile_node)
    workflow.add_node("generate_report", _generate_report_node)
    workflow.set_entry_point("aggregate_profile")
    workflow.add_edge("aggregate_profile", "generate_report")
    workflow.add_edge("generate_report", END)
    return workflow


__all__ = ["ProfileWorkflowState", "build_profile_workflow_graph"]
