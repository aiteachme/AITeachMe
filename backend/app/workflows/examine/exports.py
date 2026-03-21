"""Workflow graph exports for examine workflows."""

from __future__ import annotations

from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.examine.graph import build_examine_workflow_graph

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="examine_flow",
        title="Examine Workflow",
        description="Minimal exam generation and grading workflow.",
        build_graph=build_examine_workflow_graph,
    ),
)
