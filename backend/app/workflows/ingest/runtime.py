"""Ingest workflow runtime entrypoints."""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.common.events import InProcessEventBus
from app.workflows.common.result import WorkflowResult, err_result
from app.workflows.common.runtime import run_state_graph
from app.workflows.ingest.events import IngestFileParseFailedEvent, IngestParseRequestedEvent
from app.workflows.ingest.graph import build_parse_file_graph
from app.workflows.ingest.state import IngestParseState


def create_parse_file_initial_state(*, subject: str, file_id: int) -> IngestParseState:
    """Create the initial state for a single-file ingest workflow."""

    return {
        "subject": subject,
        "file_id": file_id,
        "error": None,
    }


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
        parse_plan = final_state.get("parse_plan")
        return err_result(
            "ingest_parse_failed",
            error_message,
            metadata={
                "subject": subject,
                "file_id": file_id,
                "filename": final_state.get("filename"),
                "filetype": final_state.get("filetype"),
                "parse_mode": parse_plan.mode if parse_plan else None,
                "parser_chain": parse_plan.parser_chain if parse_plan else None,
            },
        )
    return result
