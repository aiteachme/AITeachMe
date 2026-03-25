"""Support helpers for digest graph workflow nodes."""

from __future__ import annotations

import structlog

from app.core.database import managed_session
from app.workflows.digest.kg.state import KGDigestState

logger = structlog.get_logger()


def workflow_logger(state: KGDigestState) -> structlog.stdlib.BoundLogger:
    """Bind consistent log context for the graph digest workflow."""

    return logger.bind(
        subject=state["subject"],
        job_id=state["job_id"],
        file_ids=state.get("file_ids", []),
    )


def open_managed_session():
    """Tiny seam to keep node modules focused on orchestration."""

    return managed_session()


__all__ = [
    "open_managed_session",
    "workflow_logger",
]
