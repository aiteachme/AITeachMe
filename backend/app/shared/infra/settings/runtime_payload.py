"""Helpers for the persisted runtime settings row.

The `system_runtime_settings` table stores product settings plus local runtime
environment overrides.  The env override layer lets the local Settings UI avoid
rewriting `.env`: `.env` remains a bootstrap/default source, and non-empty DB
values win per key once the user edits them in the app.  Blank values are not
stored as overrides; they mean "fall back to `.env` / process env".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RUNTIME_ENV_OVERRIDES_KEY = "__env_overrides__"


def _normalize_env_overrides(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}

    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        text = "" if raw_value is None else str(raw_value)
        if not text.strip():
            continue
        normalized[key] = text
    return normalized


def split_runtime_settings_payload(
    payload: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    raw_payload = dict(payload or {})
    raw_env_overrides = raw_payload.pop(RUNTIME_ENV_OVERRIDES_KEY, {})
    return raw_payload, _normalize_env_overrides(raw_env_overrides)


def combine_runtime_settings_payload(
    settings_payload: Mapping[str, Any] | None,
    env_overrides: Mapping[str, str | None] | None,
) -> dict[str, Any]:
    payload = dict(settings_payload or {})
    normalized_env = _normalize_env_overrides(env_overrides)
    if normalized_env:
        payload[RUNTIME_ENV_OVERRIDES_KEY] = normalized_env
    return payload


__all__ = [
    "RUNTIME_ENV_OVERRIDES_KEY",
    "combine_runtime_settings_payload",
    "split_runtime_settings_payload",
]
