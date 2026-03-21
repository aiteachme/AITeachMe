"""Build LangGraph StateGraph objects from shared topology specs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END, StateGraph

from app.workflows.common.topology import TERMINAL_NODE, WorkflowDiagramSpec


def _resolve_target(target: str) -> Any:
    return END if target == TERMINAL_NODE else target


def build_state_graph_from_topology(
    *,
    state_type: Any,
    node_map: Mapping[str, Any],
    route_map: Mapping[str, Callable[[Any], str]],
    spec: WorkflowDiagramSpec,
) -> StateGraph:
    """Build a LangGraph StateGraph from a shared topology definition."""

    workflow = StateGraph(state_type)
    for node_name in spec.nodes:
        workflow.add_node(node_name, node_map[node_name])

    workflow.set_entry_point(spec.entry_point)
    for conditional_edge in spec.conditional_edges:
        workflow.add_conditional_edges(
            conditional_edge.source,
            route_map[conditional_edge.source],
            {
                route_name: _resolve_target(target)
                for route_name, target in conditional_edge.mapping.items()
            },
        )
    for edge in spec.edges:
        workflow.add_edge(edge.source, _resolve_target(edge.target))
    return workflow
