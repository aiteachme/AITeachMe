"""Small authoring helpers for ingest LangGraph node tracing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.infra.workflow import WorkflowTraceBinding


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
    passthrough_keys: tuple[str, ...] = ("routing", "phase"),
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


def traced_ingest_node(
    trace: WorkflowTraceBinding,
    *,
    node_key: str,
    display_name: str,
    details: Mapping[str, Any],
    handler,
    timing_field: str | None = None,
):
    """Wrap one ingest node with consistent trace metadata."""

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
    "traced_ingest_node",
]
