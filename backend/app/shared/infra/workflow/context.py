"""Workflow execution context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.shared.infra.workflow.events import InProcessEventBus

logger = structlog.get_logger()

LANGGRAPH_DEV_SUBJECT_ID = "__langgraph_dev__"
LOGGER_METADATA_RESERVED_KEYS = frozenset({"workflow", "subject_id", "correlation_id"})


@dataclass(slots=True)
class WorkflowContext:
    """Shared runtime context for one workflow run."""

    workflow_name: str
    subject_id: str
    event_bus: InProcessEventBus = field(default_factory=InProcessEventBus)
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def get_logger(self) -> structlog.stdlib.BoundLogger:
        """Return a logger pre-bound with workflow-level metadata."""

        metadata = {
            key: value
            for key, value in self.metadata.items()
            if key not in LOGGER_METADATA_RESERVED_KEYS
        }
        return logger.bind(
            workflow=self.workflow_name,
            subject_id=self.subject_id,
            correlation_id=self.correlation_id,
            **metadata,
        )


def create_langgraph_dev_context(workflow_name: str) -> WorkflowContext:
    """Create a minimal workflow context for ``langgraph dev`` debugging."""

    return WorkflowContext(
        workflow_name=workflow_name,
        subject_id=LANGGRAPH_DEV_SUBJECT_ID,
    )
