"""Routing helpers for the digest graph workflow."""

from __future__ import annotations

from app.workflows.digest.kg_file_ingest.state import KGDigestState


def _named_route(fn, name: str):
    fn.__name__ = name
    fn.__qualname__ = name
    return fn


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


def route_after_lock_for_trace(state: KGDigestState) -> str:
    return route_after_lock(state)


def route_after_prepare_for_trace(state: KGDigestState) -> str:
    return route_after_prepare(state)


def route_after_step_for_trace(state: KGDigestState) -> str:
    return route_after_step(state)


route_after_lock_for_trace = _named_route(route_after_lock_for_trace, "检查锁与入口")
route_after_prepare_for_trace = _named_route(route_after_prepare_for_trace, "检查是否有可处理分块")
route_after_step_for_trace = _named_route(route_after_step_for_trace, "检查是否继续")


__all__ = [
    "route_after_lock",
    "route_after_lock_for_trace",
    "route_after_prepare",
    "route_after_prepare_for_trace",
    "route_after_step",
    "route_after_step_for_trace",
]
