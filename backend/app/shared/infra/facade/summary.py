"""Runtime summary facade."""

from __future__ import annotations

from typing import Any

from app.shared.infra.observability.llm_stats import get_tracker
from app.shared.infra.tools.api import ensure_project_tool_modules_loaded
from app.shared.infra.tools.registry import get_tool_registry

from .context import InfraContext


def get_runtime_summary(ctx: InfraContext) -> dict[str, Any]:
    """Return lightweight infra runtime summary for diagnostics."""

    ensure_project_tool_modules_loaded()
    return {
        "context": ctx.trace_metadata(
            subject=ctx.subject,
            workflow=ctx.workflow,
            lane=ctx.lane,
            node=ctx.node,
            build_session_id=ctx.build_session_id,
        ),
        "llm": get_tracker().get_summary(
            subject=ctx.subject or None,
            build_session_id=ctx.build_session_id or None,
            workflow=ctx.workflow or None,
            lane=ctx.lane or None,
            node=ctx.node or None,
        ),
        "tools": {
            "registered_count": len(get_tool_registry().list_all()),
            "registered_names": sorted(get_tool_registry().names),
        },
    }


__all__ = ["get_runtime_summary"]
