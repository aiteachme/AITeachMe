"""Planner SSE/progress helpers."""

from __future__ import annotations

import inspect
from typing import Any, Mapping


async def _invoke_callback(callback: Any, payload: Any) -> None:
    if callback is None or not callable(callback):
        return
    try:
        result = callback(payload)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return


def _build_event_message(
    *,
    event: str,
    detail: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": event,
        "step": event,
        "event": event,
        "detail": detail,
        **(payload or {}),
    }


async def emit_planner_event(
    state: Mapping[str, Any],
    *,
    event: str,
    detail: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await _invoke_callback(
        state.get("progress_callback"),
        _build_event_message(event=event, detail=detail, payload=payload),
    )


async def emit_planner_token(state: Mapping[str, Any], token: str) -> None:
    if not token:
        return
    await _invoke_callback(state.get("token_callback"), token)


__all__ = ["emit_planner_event", "emit_planner_token"]
