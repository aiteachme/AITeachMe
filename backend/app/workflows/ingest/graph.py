"""Ingest workflow graph definitions — two-phase architecture.

Phase 1 (Fast Parse): Traditional parsing, no LLM.
Phase 2 (Deep Enhance): LLM Vision OCR, runs in background.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.workflows.common.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.common import workflow_tracer
from app.workflows.ingest.nodes.enhance import (
    build_deep_enhance_file_node,
    build_finalize_deep_enhance_node,
    build_finalize_enhance_failure_node,
    build_load_enhance_context_node,
)
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
from app.workflows.ingest.state import IngestEnhanceState, IngestParseState


def _route_after_step(state: dict) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


def build_fast_parse_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the Phase 1 fast-parse workflow (no LLM calls)."""

    workflow = StateGraph(IngestParseState)
    trace = workflow_tracer(context=context, lane="fast_parse")
    workflow.add_node(
        "load_raw_file",
        trace.node(
            build_load_raw_file_node(context=context),
            name="load_raw_file",
        ),
    )
    workflow.add_node(
        "compute_fingerprint",
        trace.node(
            build_compute_fingerprint_node(context=context),
            name="compute_fingerprint",
        ),
    )
    workflow.add_node(
        "classify_file",
        trace.node(
            build_classify_file_node(context=context),
            name="classify_file",
        ),
    )
    workflow.add_node(
        "plan_parse",
        trace.node(
            build_plan_parse_node(context=context),
            name="plan_parse",
        ),
    )
    workflow.add_node(
        "parse_file",
        trace.node(
            build_parse_file_node(context=context),
            name="parse_file",
        ),
    )
    workflow.add_node(
        "finalize_success",
        trace.node(
            build_finalize_success_node(context=context),
            name="finalize_success",
        ),
    )
    workflow.add_node(
        "finalize_failure",
        trace.node(
            build_finalize_failure_node(context=context),
            name="finalize_failure",
        ),
    )

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

def build_deep_enhance_graph() -> StateGraph:
    """Build the Phase 2 deep-enhance workflow (LLM Vision OCR)."""

    workflow = StateGraph(IngestEnhanceState)
    trace = workflow_tracer(workflow="ingest.deep_enhance", lane="deep_enhance")
    workflow.add_node(
        "load_enhance_context",
        trace.node(
            build_load_enhance_context_node(),
            name="load_enhance_context",
        ),
    )
    workflow.add_node(
        "deep_enhance_file",
        trace.node(
            build_deep_enhance_file_node(),
            name="deep_enhance_file",
        ),
    )
    workflow.add_node(
        "finalize_deep_enhance",
        trace.node(
            build_finalize_deep_enhance_node(),
            name="finalize_deep_enhance",
        ),
    )
    workflow.add_node(
        "finalize_enhance_failure",
        trace.node(
            build_finalize_enhance_failure_node(),
            name="finalize_enhance_failure",
        ),
    )

    workflow.set_entry_point("load_enhance_context")
    workflow.add_conditional_edges(
        "load_enhance_context",
        _route_after_step,
        {
            "continue": "deep_enhance_file",
            "fail": "finalize_enhance_failure",
        },
    )
    workflow.add_conditional_edges(
        "deep_enhance_file",
        _route_after_step,
        {
            "continue": "finalize_deep_enhance",
            "fail": "finalize_enhance_failure",
        },
    )
    workflow.add_conditional_edges(
        "finalize_deep_enhance",
        _route_after_step,
        {
            "continue": END,
            "fail": "finalize_enhance_failure",
        },
    )
    workflow.add_edge("finalize_enhance_failure", END)
    return workflow

# Legacy alias for backwards compatibility
def build_parse_file_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the single-file ingest workflow (legacy alias for fast parse)."""
    return build_fast_parse_graph(context=context)


def get_langgraph_dev_fast_parse_graph() -> StateGraph:
    """Create the fast-parse graph used by ``langgraph dev``."""

    return build_fast_parse_graph(
        context=create_langgraph_dev_context("ingest.file.parse.langgraph_dev"),
    )

