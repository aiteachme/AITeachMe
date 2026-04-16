"""Workflow export definitions shared by ingest lanes."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.ingest.common.parsing.prompts import PROMPTS
from app.workflows.ingest.deep_enhance.graph import build_deep_enhance_graph
from app.workflows.ingest.fast_parse.graph import build_fast_parse_graph


def _build_export_parse_graph():
    context = WorkflowContext(
        workflow_name="ingest.file.parse.export",
        subject="diagram-preview",
        event_bus=InProcessEventBus(),
        metadata={},
    )
    return build_fast_parse_graph(context=context)


def _build_export_deep_enhance_graph():
    context = WorkflowContext(
        workflow_name="ingest.deep_enhance.export",
        subject="diagram-preview",
        event_bus=InProcessEventBus(),
        metadata={},
    )
    return build_deep_enhance_graph(context=context)


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
        build_graph=_build_export_deep_enhance_graph,
        prompts=PROMPTS,
    ),
)


__all__ = ["WORKFLOW_EXPORTS"]
