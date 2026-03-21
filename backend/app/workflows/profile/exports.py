"""Workflow graph exports for profile workflows."""

from __future__ import annotations

from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.profile.graph import build_profile_workflow_graph

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="profile_flow",
        title="Profile Workflow",
        description="Minimal profile aggregation and report workflow.",
        build_graph=build_profile_workflow_graph,
    ),
)
