"""Small authoring helpers for digest LangGraph node tracing."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Mapping
from typing import Any

from app.shared.infra.workflow import WorkflowTraceBinding
from app.shared.infra.workflow.runtime import run_sync_and_drain


def named_route(fn, name: str):
    """Give a route function a readable name for LangGraph/LangSmith views."""

    fn.__name__ = name
    fn.__qualname__ = name
    return fn


def node_metadata(
    *,
    node_key: str,
    display_name: str,
    details: Mapping[str, Any],
    passthrough_keys: tuple[str, ...] = ("fanout", "fanin", "routing"),
) -> dict[str, object]:
    """Build stable metadata for both LangGraph node metadata and trace spans."""

    metadata: dict[str, object] = {
        "node_key": node_key,
        "node_display_name": display_name,
        "node_description": str(details.get("description") or ""),
        "reads": list(details.get("reads") or []),
        "writes": list(details.get("writes") or []),
        "state_inputs": list(details.get("input_keys") or []),
        "state_outputs": list(details.get("output_keys") or []),
    }
    for key in passthrough_keys:
        value = details.get(key)
        if value:
            metadata[key] = str(value)
    return metadata


def traced_digest_node(
    trace: WorkflowTraceBinding,
    *,
    node_key: str,
    display_name: str,
    details: Mapping[str, Any],
    handler,
    timing_field: str | None = None,
):
    """Wrap one digest node with consistent trace metadata."""

    if not inspect.iscoroutinefunction(handler):
        sync_handler = handler

        @functools.wraps(sync_handler)
        async def handler(state):
            result = await run_sync_and_drain(sync_handler, state)
            return await result if inspect.isawaitable(result) else result

    input_keys = list(details.get("input_keys") or [])
    output_keys = list(details.get("output_keys") or [])
    return trace.node(
        handler,
        name=node_key,
        display_name=display_name,
        description=str(details.get("description") or ""),
        timing_field=timing_field,
        input_keys=input_keys,
        output_keys=output_keys,
        metadata=node_metadata(node_key=node_key, display_name=display_name, details=details),
    )


__all__ = [
    "named_route",
    "node_metadata",
    "traced_digest_node",
]
