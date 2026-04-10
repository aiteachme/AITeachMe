"""Workflow graph exports for interact workflows."""

from __future__ import annotations

from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.interact.graph import get_langgraph_dev_interact_graph
from app.workflows.interact.prompts.prompts import PROMPTS

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="interact_flow",
        title="Interact Workflow",
        description="Teaching chat workflow with history loading, retrieval, strategy selection, prompt assembly, streaming, and persistence.",
        build_graph=get_langgraph_dev_interact_graph,
        prompts=PROMPTS,
    ),
)
