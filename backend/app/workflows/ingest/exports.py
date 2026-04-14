"""Workflow graph exports for ingest workflows."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow import WorkflowGraphExport
from app.workflows.ingest.graph import build_parse_file_graph, build_deep_enhance_graph
from app.workflows.ingest.prompts.prompts import PROMPTS


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
        prompts=PROMPTS,
    ),
    WorkflowGraphExport(
        key="ingest_deep_enhance",
        title="Ingest Deep Enhance Workflow",
        description="Background deep OCR and enhancement workflow.",
        build_graph=build_deep_enhance_graph,
        prompts=PROMPTS,
    ),
)


