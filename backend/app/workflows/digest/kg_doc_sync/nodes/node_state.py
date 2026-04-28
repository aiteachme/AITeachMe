"""Small state helpers shared by kg_doc_sync nodes.

Every node records its own entry under ``state["node_metrics"][node_key]``.
The graph routes only on ``state["error"]``; this keeps node bodies readable
and makes success/error output shape consistent across the lane.
"""

from __future__ import annotations

from app.workflows.digest.kg_doc_sync.state import DocsSyncState


def with_node_metrics(
    state: DocsSyncState,
    node_key: str,
    metrics: dict[str, object],
    **updates: object,
) -> DocsSyncState:
    node_metrics = dict(state.get("node_metrics") or {})
    node_metrics[node_key] = metrics
    return {**state, "node_metrics": node_metrics, **updates}


def with_node_error(
    state: DocsSyncState,
    node_key: str,
    error: str,
    *,
    metrics: dict[str, object] | None = None,
    **updates: object,
) -> DocsSyncState:
    return with_node_metrics(
        state,
        node_key,
        {
            "ok": False,
            "error": error,
            **dict(metrics or {}),
        },
        error=error,
        **updates,
    )


__all__ = ["with_node_error", "with_node_metrics"]
