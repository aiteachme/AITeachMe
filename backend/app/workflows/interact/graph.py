"""Minimal LangGraph definition for interact workflows."""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from app.workflows.interact.state import InteractWorkflowState


def _retrieve_context_node(state: InteractWorkflowState) -> InteractWorkflowState:
    return {**state, "retrieved": True}


def _stream_response_node(state: InteractWorkflowState) -> InteractWorkflowState:
    return {**state, "responded": True}


def build_interact_workflow_graph() -> StateGraph:
    """Build a tiny graph for the interact domain."""

    workflow = StateGraph(InteractWorkflowState)
    workflow.add_node("retrieve_context", _retrieve_context_node)
    workflow.add_node("stream_response", _stream_response_node)
    workflow.set_entry_point("retrieve_context")
    workflow.add_edge("retrieve_context", "stream_response")
    workflow.add_edge("stream_response", END)
    return workflow


__all__ = ["InteractWorkflowState", "build_interact_workflow_graph"]
