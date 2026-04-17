"""Fast-parse ingest graph."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.workflows.ingest.common.parsing.prompts import PROMPTS
from app.workflows.ingest.fast_parse.nodes import (
    build_classify_file_node,
    build_compute_fingerprint_node,
    build_finalize_failure_node,
    build_finalize_success_node,
    build_load_raw_file_node,
    build_parse_file_node,
    build_plan_parse_node,
)
from app.workflows.ingest.fast_parse.state import IngestParseState


def _route_after_step(state: dict) -> str:
    return "fail" if state.get("error") else "continue"


def build_fast_parse_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the Phase 1 fast-parse workflow (no LLM calls)."""

    workflow = StateGraph(IngestParseState)
    trace = workflow_tracer(context=context, lane="fast_parse")
    workflow.add_node(
        "load_raw_file",
        trace.node(build_load_raw_file_node(context=context), name="load_raw_file"),
    )
    workflow.add_node(
        "compute_fingerprint",
        trace.node(build_compute_fingerprint_node(context=context), name="compute_fingerprint"),
    )
    workflow.add_node(
        "classify_file",
        trace.node(build_classify_file_node(context=context), name="classify_file"),
    )
    workflow.add_node(
        "plan_parse",
        trace.node(build_plan_parse_node(context=context), name="plan_parse"),
    )
    workflow.add_node(
        "parse_file",
        trace.node(build_parse_file_node(context=context), name="parse_file"),
    )
    workflow.add_node(
        "finalize_success",
        trace.node(build_finalize_success_node(context=context), name="finalize_success"),
    )
    workflow.add_node(
        "finalize_failure",
        trace.node(build_finalize_failure_node(context=context), name="finalize_failure"),
    )

    workflow.set_entry_point("load_raw_file")
    workflow.add_conditional_edges("load_raw_file", _route_after_step, {"continue": "compute_fingerprint", "fail": "finalize_failure"})
    workflow.add_conditional_edges("compute_fingerprint", _route_after_step, {"continue": "classify_file", "fail": "finalize_failure"})
    workflow.add_conditional_edges("classify_file", _route_after_step, {"continue": "plan_parse", "fail": "finalize_failure"})
    workflow.add_conditional_edges("plan_parse", _route_after_step, {"continue": "parse_file", "fail": "finalize_failure"})
    workflow.add_conditional_edges("parse_file", _route_after_step, {"continue": "finalize_success", "fail": "finalize_failure"})
    workflow.add_conditional_edges("finalize_success", _route_after_step, {"continue": END, "fail": "finalize_failure"})
    workflow.add_edge("finalize_failure", END)
    return workflow


def get_langgraph_dev_fast_parse_graph() -> StateGraph:
    return build_fast_parse_graph(
        context=create_langgraph_dev_context("ingest.fast_parse.langgraph_dev"),
    )


def build_parse_file_graph(*, context: WorkflowContext) -> StateGraph:
    """Legacy alias kept at lane level so the module root can disappear."""

    return build_fast_parse_graph(context=context)


def _build_export_graph() -> StateGraph:
    return build_fast_parse_graph(
        context=create_langgraph_dev_context("ingest.fast_parse.export"),
    )


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="ingest_parse",
        title="Ingest File Parse Workflow",
        description="Single-file ingest parsing workflow.",
        build_graph=_build_export_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "WORKFLOW_EXPORTS",
    "build_fast_parse_graph",
    "build_parse_file_graph",
    "get_langgraph_dev_fast_parse_graph",
]
