"""Shared ingest workflow helpers."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.ingest.fast_parse.state import IngestParseState


def workflow_logger(context: WorkflowContext, state: IngestParseState):
    return context.get_logger().bind(
        file_id=state["file_id"],
        filename=state.get("filename"),
    )
