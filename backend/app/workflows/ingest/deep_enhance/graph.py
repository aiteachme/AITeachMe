"""Deep-enhance ingest graph."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.ingest.common.parsing.prompts import PROMPTS
from app.workflows.ingest.deep_enhance.nodes import (
    build_deep_enhance_file_node,
    build_finalize_deep_enhance_node,
    build_finalize_enhance_failure_node,
    build_load_enhance_context_node,
)
from app.workflows.ingest.deep_enhance.state import IngestEnhanceState


def _route_after_step(state: dict) -> str:
    return "fail" if state.get("error") else "continue"


def build_deep_enhance_graph(*, context: WorkflowContext | None = None) -> StateGraph:
    """Build the Phase 2 deep-enhance workflow."""

    workflow_context = context or create_langgraph_dev_context("ingest.deep_enhance.langgraph_dev")
    workflow = StateGraph(IngestEnhanceState)
    trace = workflow_tracer(context=workflow_context, lane="deep_enhance")
    workflow.add_node(
        "load_enhance_context",
        trace.node(build_load_enhance_context_node(), name="load_enhance_context"),
    )
    workflow.add_node(
        "deep_enhance_file",
        trace.node(build_deep_enhance_file_node(), name="deep_enhance_file"),
    )
    workflow.add_node(
        "finalize_deep_enhance",
        trace.node(build_finalize_deep_enhance_node(), name="finalize_deep_enhance"),
    )
    workflow.add_node(
        "finalize_enhance_failure",
        trace.node(build_finalize_enhance_failure_node(), name="finalize_enhance_failure"),
    )

    workflow.set_entry_point("load_enhance_context")
    workflow.add_conditional_edges("load_enhance_context", _route_after_step, {"continue": "deep_enhance_file", "fail": "finalize_enhance_failure"})
    workflow.add_conditional_edges("deep_enhance_file", _route_after_step, {"continue": "finalize_deep_enhance", "fail": "finalize_enhance_failure"})
    workflow.add_conditional_edges("finalize_deep_enhance", _route_after_step, {"continue": END, "fail": "finalize_enhance_failure"})
    workflow.add_edge("finalize_enhance_failure", END)
    return workflow


def get_langgraph_dev_deep_enhance_graph() -> StateGraph:
    return build_deep_enhance_graph(
        context=create_langgraph_dev_context("ingest.deep_enhance.langgraph_dev"),
    )


def _build_export_graph() -> StateGraph:
    return build_deep_enhance_graph(
        context=create_langgraph_dev_context("ingest.deep_enhance.export"),
    )


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="ingest_deep_enhance",
        title="Ingest Deep Enhance Workflow",
        description="Background deep OCR and enhancement workflow.",
        build_graph=_build_export_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "WORKFLOW_EXPORTS",
    "build_deep_enhance_graph",
    "get_langgraph_dev_deep_enhance_graph",
]
