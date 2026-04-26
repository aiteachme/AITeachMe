"""Minimal workflow progress helper for frontend-facing status events."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any


async def emit_progress(
    state: Mapping[str, Any],
    *,
    stage: str,
    detail: str,
    step: str | None = None,
    elapsed_ms: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Emit one compact progress event without coupling it to tracing."""

    callback = state.get("progress_callback")
    if callback is None or not callable(callback):
        return

    payload: dict[str, Any] = {
        "stage": str(stage or "").strip(),
        "detail": str(detail or "").strip(),
    }
    if step is not None and str(step).strip():
        payload["step"] = str(step).strip()
    if elapsed_ms is not None:
        payload["elapsed_ms"] = int(elapsed_ms)
    if extra:
        payload.update(dict(extra))

    try:
        maybe_awaitable = callback(payload)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except Exception:
        return


__all__ = ["emit_progress"]
