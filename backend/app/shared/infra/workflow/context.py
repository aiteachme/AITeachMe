"""Workflow execution context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.shared.infra.workflow.events import InProcessEventBus

logger = structlog.get_logger()

LANGGRAPH_DEV_SUBJECT = "__langgraph_dev__"


@dataclass(slots=True)
class WorkflowContext:
    """Shared runtime context for one workflow run."""

    workflow_name: str
    subject: str
    event_bus: InProcessEventBus = field(default_factory=InProcessEventBus)
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def get_logger(self) -> structlog.stdlib.BoundLogger:
        """Return a logger pre-bound with workflow-level metadata."""

        return logger.bind(
            workflow=self.workflow_name,
            subject=self.subject,
            correlation_id=self.correlation_id,
            **self.metadata,
        )


def create_langgraph_dev_context(workflow_name: str) -> WorkflowContext:
    """Create a minimal workflow context for ``langgraph dev`` debugging."""

    return WorkflowContext(
        workflow_name=workflow_name,
        subject=LANGGRAPH_DEV_SUBJECT,
    )

