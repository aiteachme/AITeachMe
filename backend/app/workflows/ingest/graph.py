"""Ingest workflow graph entrypoints."""

from __future__ import annotations

from langgraph.graph import StateGraph

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.result import WorkflowResult, err_result
from app.workflows.common.runtime import run_state_graph
from app.workflows.common.state_graph_builder import build_state_graph_from_topology
from app.workflows.ingest.diagrams import INGEST_PARSE_DIAGRAM, WORKFLOW_DIAGRAMS
from app.workflows.ingest.events import IngestFileParseFailedEvent, IngestParseRequestedEvent
from app.workflows.ingest.nodes import (
    build_classify_file_node,
    build_compute_fingerprint_node,
    build_finalize_failure_node,
    build_finalize_success_node,
    build_load_raw_file_node,
    build_parse_file_node,
)
from app.workflows.ingest.state import IngestParseState


def _route_after_step(state: IngestParseState) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


_INGEST_ROUTE_MAP = {
    "load_raw_file": _route_after_step,
    "compute_fingerprint": _route_after_step,
    "classify_file": _route_after_step,
    "parse_file": _route_after_step,
    "finalize_success": _route_after_step,
}


def create_parse_file_initial_state(*, subject: str, file_id: int) -> IngestParseState:
    """Create the initial state for a single-file ingest workflow."""

    return {
        "subject": subject,
        "file_id": file_id,
        "error": None,
    }


def build_parse_file_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the single-file ingest workflow."""

    node_map = {
        "load_raw_file": build_load_raw_file_node(context=context),
        "compute_fingerprint": build_compute_fingerprint_node(context=context),
        "classify_file": build_classify_file_node(context=context),
        "parse_file": build_parse_file_node(context=context),
        "finalize_success": build_finalize_success_node(context=context),
        "finalize_failure": build_finalize_failure_node(context=context),
    }
    return build_state_graph_from_topology(
        state_type=IngestParseState,
        node_map=node_map,
        route_map=_INGEST_ROUTE_MAP,
        spec=INGEST_PARSE_DIAGRAM,
    )


async def run_parse_file_workflow(
    *,
    subject: str,
    file_id: int,
    event_bus: InProcessEventBus | None = None,
) -> WorkflowResult[IngestParseState]:
    """Run the ingest workflow for one raw file."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(IngestParseRequestedEvent(subject=subject, file_id=file_id))
    context = WorkflowContext(
        workflow_name="ingest.file.parse",
        subject=subject,
        event_bus=bus,
        metadata={"file_id": file_id},
    )
    result = await run_state_graph(
        workflow_name="ingest.file.parse",
        graph_builder=lambda: build_parse_file_graph(context=context),
        initial_state=create_parse_file_initial_state(subject=subject, file_id=file_id),
        context=context,
    )
    if result.failed:
        await bus.publish(
            IngestFileParseFailedEvent(
                subject=subject,
                file_id=file_id,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    error_message = final_state.get("error")
    if error_message:
        return err_result(
            "ingest_parse_failed",
            error_message,
            metadata={"subject": subject, "file_id": file_id},
        )
    return result
