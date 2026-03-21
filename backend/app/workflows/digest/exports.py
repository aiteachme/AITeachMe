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


# Send 动态边 + Fan-Out 子节点下游边：draw_mermaid 无法自动导出
_DOCGEN_SEND_EDGES = (
    "outline_reduce -. &nbsp;Send&nbsp;×N&nbsp; .-> draft_chapter",
    "draft_chapter --> collect_drafts",
    "collect_drafts -. &nbsp;Send&nbsp;×N&nbsp; .-> review_chapter",
    "review_chapter --> collect_reviews",
    "collect_reviews -. &nbsp;Send&nbsp;×N&nbsp; .-> extract_metadata",
    "extract_metadata --> finalize_assemble",
    "finalize_assemble --> __end__",
)

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
        description="Knowledge document generation workflow with Fan-Out parallelism.",
        build_graph=_build_docgen_graph_for_export,
        extra_edges=_DOCGEN_SEND_EDGES,
    ),
)
