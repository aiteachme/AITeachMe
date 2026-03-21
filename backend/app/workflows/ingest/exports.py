"""Workflow graph exports for ingest workflows."""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.graph_export import WorkflowGraphExport
from app.workflows.ingest.graph import build_parse_file_graph


def _build_export_parse_graph():
    context = WorkflowContext(
        workflow_name="ingest.file.parse.export",
        subject="diagram-preview",
        event_bus=InProcessEventBus(),
        metadata={},
    )
    return build_parse_file_graph(context=context)


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="ingest_parse",
        title="Ingest File Parse Workflow",
        description="Single-file ingest parsing workflow.",
        build_graph=_build_export_parse_graph,
    ),
)
