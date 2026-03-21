"""Workflow graph exports for digest workflows."""

from __future__ import annotations

from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.digest.graph import build_curriculum_derive_graph, build_kg_digest_graph

WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="digest_graph",
        title="Digest Graph Workflow",
        description="Incremental knowledge-graph build workflow.",
        build_graph=build_kg_digest_graph,
    ),
    WorkflowGraphExport(
        key="digest_curriculum",
        title="Digest Curriculum Workflow",
        description="Curriculum derivation workflow built from digest graph impact.",
        build_graph=build_curriculum_derive_graph,
    ),
)
