"""Workflow 执行上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import uuid

import structlog

from app.workflows.common.events import InProcessEventBus

logger = structlog.get_logger()


@dataclass(slots=True)
class WorkflowContext:
    """统一的 workflow 执行上下文。"""

    workflow_name: str
    subject: str
    event_bus: InProcessEventBus = field(default_factory=InProcessEventBus)
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def get_logger(self) -> structlog.stdlib.BoundLogger:
        """为当前 workflow 绑定统一日志上下文。"""

        return logger.bind(
            workflow=self.workflow_name,
            subject=self.subject,
            correlation_id=self.correlation_id,
            **self.metadata,
        )

