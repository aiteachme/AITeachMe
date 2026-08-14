"""Small state helpers shared by kg_doc_sync nodes.

Every node records its own entry under ``state["node_metrics"][node_key]``.
The graph routes only on ``state["error"]``; this keeps node bodies readable
and makes success/error output shape consistent across the lane.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from sqlmodel import Session

from app.shared.infra.knowledge.build_store import managed_knowledge_build_owner_transaction
from app.workflows.digest.kg_doc_sync.state import DocsSyncState


_ALLOWED_BUILD_LOCK_PHASES = {"active", "published"}


def managed_build_owner_transaction(state: DocsSyncState) -> AbstractContextManager[Session]:
    """Fence one KG write transaction through its database commit."""

    build_group_id = str(state.get("build_group_id") or "").strip()
    build_lock_phase = str(state.get("build_lock_phase") or "").strip()
    if not build_group_id or build_lock_phase not in _ALLOWED_BUILD_LOCK_PHASES:
        raise RuntimeError("knowledge_build_lock_context_missing")
    return managed_knowledge_build_owner_transaction(
        state["course_id"],
        build_group_id=build_group_id,
        allowed_phases=(build_lock_phase,),
    )


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


__all__ = ["managed_build_owner_transaction", "with_node_error", "with_node_metrics"]
