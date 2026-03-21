"""Workflow graph exports for digest workflows."""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.digest.graph import (
    build_curriculum_derive_graph,
    build_docgen_graph,
    build_kg_digest_graph,
)


def _build_docgen_graph_for_export():
    """为导出/图表生成包装 build_docgen_graph（提供默认 context）。"""

    ctx = WorkflowContext(
        workflow_name="digest.docgen",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_docgen_graph(context=ctx)


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
    WorkflowGraphExport(
        key="digest_docgen",
        title="Digest DocGen Workflow",
        description="Knowledge document generation workflow: cleanse → outline → draft → finalize.",
        build_graph=_build_docgen_graph_for_export,
    ),
)
