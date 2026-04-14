"""Compatibility shim for the deprecated unified digest build runtime.

This module used to host a full runtime implementation. It now forwards all
legacy imports to the active runtime in ``app.workflows.digest.unified.runtime``
so there is only one live implementation.
"""

from __future__ import annotations

from datetime import datetime

from app.shared.infra.workflow.events import InProcessEventBus
from app.workflows.digest.unified.runtime import (
    run_unified_digest_build as run_active_unified_digest_build,
)
from app.workflows.digest.unified.state import UnifiedBuildResult


async def run_unified_digest_build(
    subject: str,
    file_ids: list[int],
    user_prompt: str | None = None,
    requested_at: datetime | None = None,
    event_bus: InProcessEventBus | None = None,
) -> UnifiedBuildResult:
    """Forward deprecated calls to the active unified digest runtime."""

    return await run_active_unified_digest_build(
        subject=subject,
        file_ids=file_ids,
        user_prompt=user_prompt,
        requested_at=requested_at,
        event_bus=event_bus,
    )