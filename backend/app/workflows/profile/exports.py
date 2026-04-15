"""Workflow graph exports for profile workflows."""

from __future__ import annotations

from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.profile.graph import (
    build_profile_pipeline_graph,
    build_profile_workflow_graph,
)
from app.workflows.profile.prompts.prompts import PROMPTS

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="profile_pipeline",
        title="Profile Pipeline Workflow",
        description="Executable profile pipeline from mastery updates to review scheduling, weakness analysis, and profile refresh.",
        build_graph=build_profile_pipeline_graph,
        prompts=PROMPTS,
    ),
    WorkflowGraphExport(
        key="profile_flow",
        title="Profile Workflow",
        description="High-level profile workflow from mastery updates to review scheduling, weakness ranking, and report suggestions.",
        build_graph=build_profile_workflow_graph,
        prompts=PROMPTS,
    ),
)


