"""Small PostHog capture client for backend product events."""

from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com"
DEFAULT_POSTHOG_TIMEOUT_S = 8.0
DEFAULT_POSTHOG_RETRY_COUNT = 1
_POSTHOG_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="posthog")


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


def _env_int(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(0, int(value.strip()))
    except ValueError:
        return default


def _project_token() -> str:
    return (
        os.getenv("POSTHOG_PROJECT_TOKEN")
        or os.getenv("POSTHOG_PROJECT_API_KEY")
        or ""
    ).strip()


def _suffix(value: str | None, *, length: int = 8) -> str | None:
    normalized = str(value or "").strip()
    return normalized[-length:] if normalized else None


def _insert_id(event: str, parts: list[str]) -> str:
    normalized_parts = [event, *(part.strip() for part in parts if part and part.strip())]
    digest = hashlib.sha256(":".join(normalized_parts).encode("utf-8")).hexdigest()[:32]
    return f"{event}:{digest}"


def _timestamp_to_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat()
    normalized = str(value or "").strip()
    return normalized or None


def is_posthog_enabled() -> bool:
    return _env_flag("POSTHOG_ENABLED") and bool(_project_token())


def capture_posthog_event(
    event: str,
    *,
    distinct_id: str,
    properties: dict[str, Any] | None = None,
    timestamp: datetime | str | None = None,
) -> bool:
    """Capture one backend product event without affecting the caller on failure."""

    project_token = _project_token()
    if not _env_flag("POSTHOG_ENABLED") or not project_token:
        return False

    host = (os.getenv("POSTHOG_HOST") or DEFAULT_POSTHOG_HOST).strip().rstrip("/")
    timeout_s = _env_float("POSTHOG_TIMEOUT_S", default=DEFAULT_POSTHOG_TIMEOUT_S)
    retry_count = _env_int("POSTHOG_RETRY_COUNT", default=DEFAULT_POSTHOG_RETRY_COUNT)
    payload = {
        "api_key": project_token,
        "event": event,
        "distinct_id": distinct_id,
        "properties": properties or {},
    }
    event_timestamp = _timestamp_to_iso(timestamp)
    if event_timestamp is not None:
        payload["timestamp"] = event_timestamp

    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            response = httpx.post(f"{host}/capture/", json=payload, timeout=timeout_s, trust_env=False)
            response.raise_for_status()
            if _env_flag("POSTHOG_DEBUG"):
                logger.info(
                    "posthog_capture_succeeded",
                    posthog_event=event,
                    status_code=response.status_code,
                    attempt=attempt + 1,
                )
            return True
        except Exception as exc:  # pragma: no cover - defensive logging only
            last_error = exc
            if attempt < retry_count:
                logger.warning(
                    "posthog_capture_retrying",
                    posthog_event=event,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                time.sleep(min(0.25 * (attempt + 1), 1.0))

    if last_error is not None:
        logger.warning(
            "posthog_capture_failed",
            posthog_event=event,
            attempts=retry_count + 1,
            error=str(last_error),
        )
    return False


def capture_course_build_event(
    event: str,
    *,
    course_id: str,
    user_id: str | None,
    insert_id_parts: list[str],
    properties: dict[str, Any] | None = None,
    timestamp: datetime | str | None = None,
) -> bool:
    normalized_course_id = str(course_id or "").strip()
    normalized_user_id = str(user_id or "").strip()
    distinct_id = normalized_user_id or f"course:{normalized_course_id or 'unknown'}"
    event_properties = dict(properties or {})
    event_properties.update(
        {
            "$insert_id": _insert_id(
                event,
                [
                    normalized_course_id or "unknown_course",
                    normalized_user_id or "",
                    *insert_id_parts,
                ],
            ),
            "analytics_source": "backend",
            "user_id_present": bool(normalized_user_id),
            "user_id_suffix": _suffix(normalized_user_id),
            "course_id_present": bool(normalized_course_id),
            "course_id_suffix": _suffix(normalized_course_id),
        }
    )
    return capture_posthog_event(
        event,
        distinct_id=distinct_id,
        properties=event_properties,
        timestamp=timestamp,
    )


def capture_course_build_event_later(
    event: str,
    *,
    course_id: str,
    user_id: str | None,
    insert_id_parts: list[str],
    properties: dict[str, Any] | None = None,
    timestamp: datetime | str | None = None,
) -> Future[bool] | None:
    """Queue a course-build event without blocking the API request path."""

    if not is_posthog_enabled():
        return None

    event_timestamp = timestamp or datetime.now(timezone.utc)
    future = _POSTHOG_EXECUTOR.submit(
        capture_course_build_event,
        event,
        course_id=course_id,
        user_id=user_id,
        insert_id_parts=list(insert_id_parts),
        properties=dict(properties or {}),
        timestamp=event_timestamp,
    )

    def _log_unhandled_exception(done: Future[bool]) -> None:
        try:
            done.result()
        except Exception as exc:  # pragma: no cover - defensive executor guard
            logger.warning(
                "posthog_background_capture_failed",
                posthog_event=event,
                error=str(exc),
            )

    future.add_done_callback(_log_unhandled_exception)
    return future
