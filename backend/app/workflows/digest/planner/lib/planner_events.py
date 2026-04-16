"""Planner SSE/progress helpers."""

from __future__ import annotations

import inspect
from typing import Any, Mapping


async def emit_planner_event(
    state: Mapping[str, Any],
    *,
    event: str,
    detail: str,
    payload: dict[str, Any] | None = None,
) -> None:
    callback = state.get("progress_callback")
    if callback is None or not callable(callback):
        return

    message = {
        "stage": event,
        "step": event,
        "event": event,
        "detail": detail,
        **(payload or {}),
    }
    try:
        maybe_awaitable = callback(message)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except Exception:
        return


async def emit_planner_token(state: Mapping[str, Any], token: str) -> None:
    callback = state.get("token_callback")
    if callback is None or not callable(callback) or not token:
        return
    try:
        maybe_awaitable = callback(token)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except Exception:
        return


__all__ = ["emit_planner_event", "emit_planner_token"]
