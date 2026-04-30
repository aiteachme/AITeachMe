"""Shared helpers for Server-Sent Event responses."""

from __future__ import annotations

import math
from collections.abc import Mapping

from app.shared.infra.env_support import get_env_float

_SSE_DEFAULT_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache, no-transform",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Content-Encoding": "identity",
}


def sse_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return proxy-friendly headers for SSE endpoints."""

    headers = dict(_SSE_DEFAULT_HEADERS)
    if extra:
        headers.update({str(key): str(value) for key, value in extra.items()})
    return headers


def get_sse_interval(
    env_name: str,
    *,
    default: float,
    min_value: float = 1.0,
    max_value: float = 30.0,
) -> float:
    """Read a bounded SSE interval from the environment."""

    value = get_env_float(env_name, default)
    if not math.isfinite(value):
        return default
    return max(min_value, min(max_value, value))
