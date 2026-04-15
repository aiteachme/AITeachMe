"""Compatibility wrapper exposing the canonical interact chat graph."""

from app.workflows.interact.graph import (
    InteractWorkflowState,
    build_interact_workflow_graph,
    get_langgraph_dev_interact_graph,
)

__all__ = [
    "InteractWorkflowState",
    "build_interact_workflow_graph",
    "get_langgraph_dev_interact_graph",
]
