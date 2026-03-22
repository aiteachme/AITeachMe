"""Workflow graph exports for interact workflows."""

from __future__ import annotations

from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.interact.graph import build_interact_workflow_graph

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="interact_flow",
        title="Interact Workflow",
        description="Teaching chat workflow with history loading, retrieval, strategy selection, prompt assembly, streaming, and persistence.",
        build_graph=build_interact_workflow_graph,
    ),
)
