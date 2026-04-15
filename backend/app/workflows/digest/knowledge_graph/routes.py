"""Routing helpers for the digest graph workflow."""

from __future__ import annotations

from app.workflows.digest.knowledge_graph.state import KGDigestState


def route_after_lock(state: KGDigestState) -> str:
    if state.get("error"):
        return "fail"
    return "prepare"


def route_after_step(state: KGDigestState) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


def route_after_prepare(state: KGDigestState) -> str:
    if state.get("error"):
        return "fail"
    if not state.get("chunk_ids"):
        return "finalize_graph"
    return "extract"


__all__ = ["route_after_lock", "route_after_prepare", "route_after_step"]

