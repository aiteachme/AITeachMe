from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext


def test_workflow_context_logger_ignores_reserved_metadata_keys() -> None:
    context = WorkflowContext(
        workflow_name="ingest.fast_parse",
        subject="math",
        correlation_id="corr-1",
        metadata={
            "workflow": "metadata-workflow",
            "subject": "metadata-subject",
            "correlation_id": "metadata-correlation",
            "file_id": 1,
        },
    )

    logger = context.get_logger()

    assert logger is not None
