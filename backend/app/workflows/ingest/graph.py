"""Ingest workflow graph definition."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.workflows.common.context import WorkflowContext
from app.workflows.ingest.nodes.file import (
    build_classify_file_node,
    build_compute_fingerprint_node,
    build_load_raw_file_node,
    build_plan_parse_node,
)
from app.workflows.ingest.nodes.finalize import (
    build_finalize_failure_node,
    build_finalize_success_node,
)
from app.workflows.ingest.nodes.parse import build_parse_file_node
from app.workflows.ingest.state import IngestParseState


def _route_after_step(state: IngestParseState) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


def build_parse_file_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the single-file ingest workflow."""

    workflow = StateGraph(IngestParseState)
    workflow.add_node("load_raw_file", build_load_raw_file_node(context=context))
    workflow.add_node("compute_fingerprint", build_compute_fingerprint_node(context=context))
    workflow.add_node("classify_file", build_classify_file_node(context=context))
    workflow.add_node("plan_parse", build_plan_parse_node(context=context))
    workflow.add_node("parse_file", build_parse_file_node(context=context))
    workflow.add_node("finalize_success", build_finalize_success_node(context=context))
    workflow.add_node("finalize_failure", build_finalize_failure_node(context=context))

    workflow.set_entry_point("load_raw_file")
    workflow.add_conditional_edges(
        "load_raw_file",
        _route_after_step,
        {
            "continue": "compute_fingerprint",
            "fail": "finalize_failure",
        },
    )
    workflow.add_conditional_edges(
        "compute_fingerprint",
        _route_after_step,
        {
            "continue": "classify_file",
            "fail": "finalize_failure",
        },
    )
    workflow.add_conditional_edges(
        "classify_file",
        _route_after_step,
        {
            "continue": "plan_parse",
            "fail": "finalize_failure",
        },
    )
    workflow.add_conditional_edges(
        "plan_parse",
        _route_after_step,
        {
            "continue": "parse_file",
            "fail": "finalize_failure",
        },
    )
    workflow.add_conditional_edges(
        "parse_file",
        _route_after_step,
        {
            "continue": "finalize_success",
            "fail": "finalize_failure",
        },
    )
    workflow.add_conditional_edges(
        "finalize_success",
        _route_after_step,
        {
            "continue": END,
            "fail": "finalize_failure",
        },
    )
    workflow.add_edge("finalize_failure", END)
    return workflow
