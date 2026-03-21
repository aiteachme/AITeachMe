"""Shared workflow topology definitions and Mermaid rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

TERMINAL_NODE = "END"


@dataclass(slots=True, frozen=True)
class WorkflowEdgeSpec:
    """A direct transition between two workflow nodes."""

    source: str
    target: str


@dataclass(slots=True, frozen=True)
class WorkflowConditionalEdgeSpec:
    """A conditional transition map from one source node."""

    source: str
    mapping: dict[str, str]


@dataclass(slots=True, frozen=True)
class WorkflowDiagramSpec:
    """A reusable workflow topology for both runtime assembly and diagrams."""

    key: str
    title: str
    entry_point: str
    nodes: tuple[str, ...]
    description: str = ""
    node_labels: dict[str, str] = field(default_factory=dict)
    conditional_edges: tuple[WorkflowConditionalEdgeSpec, ...] = ()
    edges: tuple[WorkflowEdgeSpec, ...] = ()


def render_mermaid_flowchart(
    spec: WorkflowDiagramSpec,
    *,
    direction: str = "TD",
) -> str:
    """Render a workflow diagram spec into Mermaid flowchart syntax."""

    node_ids = {node_name: _sanitize_node_id(node_name) for node_name in spec.nodes}
    has_terminal = any(
        edge.target == TERMINAL_NODE for edge in spec.edges
    ) or any(
        target == TERMINAL_NODE
        for conditional_edge in spec.conditional_edges
        for target in conditional_edge.mapping.values()
    )

    lines = [f"flowchart {direction}"]
    lines.append('    workflow_start(["Start"])')
    if has_terminal:
        lines.append('    workflow_end(["End"])')

    for node_name in spec.nodes:
        label = spec.node_labels.get(node_name, node_name)
        safe_label = label.replace('"', "'")
        lines.append(f'    {node_ids[node_name]}["{safe_label}"]')

    lines.append(f"    workflow_start --> {node_ids[spec.entry_point]}")
    for conditional_edge in spec.conditional_edges:
        source_id = node_ids[conditional_edge.source]
        for route_name, target in conditional_edge.mapping.items():
            target_id = "workflow_end" if target == TERMINAL_NODE else node_ids[target]
            safe_route_name = route_name.replace('"', "'")
            lines.append(f'    {source_id} -->|"{safe_route_name}"| {target_id}')
    for edge in spec.edges:
        source_id = node_ids[edge.source]
        target_id = "workflow_end" if edge.target == TERMINAL_NODE else node_ids[edge.target]
        lines.append(f"    {source_id} --> {target_id}")

    return "\n".join(lines)


def _sanitize_node_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)
