"""Small PostHog capture client for backend product events."""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def _env_float(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(0.1, float(value.strip()))
    except ValueError:
        return default


def is_posthog_enabled() -> bool:
    return _env_flag("POSTHOG_ENABLED") and bool(os.getenv("POSTHOG_PROJECT_API_KEY", "").strip())


def capture_posthog_event(
    event: str,
    *,
    distinct_id: str,
    properties: dict[str, Any] | None = None,
) -> bool:
    """Capture one backend product event without affecting the caller on failure."""

    api_key = os.getenv("POSTHOG_PROJECT_API_KEY", "").strip()
    if not _env_flag("POSTHOG_ENABLED") or not api_key:
        return False

    host = (os.getenv("POSTHOG_HOST") or DEFAULT_POSTHOG_HOST).strip().rstrip("/")
    timeout_s = _env_float("POSTHOG_TIMEOUT_S", default=2.0)
    payload = {
        "api_key": api_key,
        "event": event,
        "distinct_id": distinct_id,
        "properties": properties or {},
    }

    try:
        response = httpx.post(f"{host}/capture/", json=payload, timeout=timeout_s)
        response.raise_for_status()
        if _env_flag("POSTHOG_DEBUG"):
            logger.info(
                "posthog_capture_succeeded",
                posthog_event=event,
                status_code=response.status_code,
            )
        return True
    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.warning(
            "posthog_capture_failed",
            posthog_event=event,
            error=str(exc),
        )
        return False
