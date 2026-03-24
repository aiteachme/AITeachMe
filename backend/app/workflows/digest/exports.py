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
from app.workflows.digest.unified.graph import build_unified_digest_graph


def _build_docgen_graph_for_export():
    """Wrap the docs graph with a minimal export context."""

    ctx = WorkflowContext(
        workflow_name="digest.docgen",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_docgen_graph(context=ctx)


def _build_unified_graph_for_export():
    """Wrap the unified graph with a minimal export context."""

    ctx = WorkflowContext(
        workflow_name="digest.unified",
        subject="__export__",
        event_bus=InProcessEventBus(),
    )
    return build_unified_digest_graph(context=ctx)


_DOCGEN_SEND_EDGES = (
    "outline_reduce -. Send xN .-> draft_chapter",
    "draft_chapter --> collect_drafts",
    "collect_drafts -. Send xN .-> review_chapter",
    "review_chapter --> collect_reviews",
    "collect_reviews -. Send xN .-> extract_metadata",
    "extract_metadata --> finalize_assemble",
    "finalize_assemble --> __end__",
)


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="digest_unified",
        title="Digest Unified Workflow",
        description="Shared prepare, docs lane, graph lane, consistency, repair, and curriculum.",
        build_graph=_build_unified_graph_for_export,
    ),
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
        description="Knowledge document generation workflow with fan-out parallelism.",
        build_graph=_build_docgen_graph_for_export,
        extra_edges=_DOCGEN_SEND_EDGES,
    ),
)
