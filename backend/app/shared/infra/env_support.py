"""Small helpers for loading and parsing environment variables.

This module does not model environment variables as one global settings object.
It only:
1. loads repo-local `.env` into `os.environ`
2. lets local DB settings override selected env keys at runtime
3. provides a few typed parsing helpers
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_FALSY_VALUES = {"0", "false", "no", "off"}
_MISSING_ENV_VALUE = object()
_RUNTIME_ENV_OVERRIDES: dict[str, str] = {}
_RUNTIME_ENV_BASE_VALUES: dict[str, str | object] = {}


def _configured_data_dir() -> Path | None:
    raw_value = os.getenv("AITEACHME_DATA_DIR")
    if not raw_value or not raw_value.strip():
        return None
    return Path(raw_value).expanduser().resolve()


def _dotenv_candidates() -> tuple[Path, ...]:
    """Return dotenv lookup paths for both repo dev and packaged desktop runs."""

    candidates: list[Path] = []
    data_dir = _configured_data_dir()
    if data_dir is not None:
        candidates.append(data_dir / ".env")
    candidates.extend(
        [
            _PROJECT_ROOT / ".env",
            _BACKEND_ROOT / ".env",
        ]
    )

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return tuple(unique)


@lru_cache(maxsize=1)
def load_local_dotenv() -> None:
    """Load repo-local `.env` values into `os.environ` if they are unset."""

    for path in _dotenv_candidates():
        if not path.exists():
            continue
        try:
            values = dotenv_values(path, encoding="utf-8")
        except Exception:
            continue
        for key, value in values.items():
            env_key = str(key or "").strip()
            if not env_key or env_key in os.environ:
                continue
            os.environ[env_key] = "" if value is None else str(value)


def get_env(name: str, default: str | None = None) -> str | None:
    load_local_dotenv()
    if name in _RUNTIME_ENV_OVERRIDES:
        return _RUNTIME_ENV_OVERRIDES[name]
    value = os.getenv(name)
    if value is None:
        return default
    return value


def set_runtime_env_overrides(overrides: Mapping[str, str | None] | None) -> None:
    """Apply DB-backed local runtime env overrides to this process."""

    load_local_dotenv()
    normalized = {
        str(key).strip(): "" if value is None else str(value)
        for key, value in dict(overrides or {}).items()
        if str(key or "").strip()
    }

    previous_keys = set(_RUNTIME_ENV_OVERRIDES)
    next_keys = set(normalized)

    for key in previous_keys - next_keys:
        base_value = _RUNTIME_ENV_BASE_VALUES.pop(key, _MISSING_ENV_VALUE)
        if base_value is _MISSING_ENV_VALUE:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(base_value)

    for key, value in normalized.items():
        if key not in _RUNTIME_ENV_BASE_VALUES:
            _RUNTIME_ENV_BASE_VALUES[key] = os.environ.get(key, _MISSING_ENV_VALUE)
        if value.strip():
            os.environ[key] = value
        else:
            os.environ.pop(key, None)

    _RUNTIME_ENV_OVERRIDES.clear()
    _RUNTIME_ENV_OVERRIDES.update(normalized)


def get_env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw_value = get_env(name)
    if raw_value is None:
        return list(default or [])

    values: list[str] = []
    seen: set[str] = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values or list(default or [])


def get_env_choice(name: str, default: str | None = None) -> str | None:
    values = get_env_list(name)
    if not values:
        return default
    return secrets.choice(values)


def get_env_bool(name: str, default: bool) -> bool:
    raw_value = get_env(name)
    if raw_value is None or not raw_value.strip():
        return default
    normalized = raw_value.strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    return default


def get_env_optional_bool(name: str) -> bool | None:
    raw_value = get_env(name)
    if raw_value is None or not raw_value.strip():
        return None
    normalized = raw_value.strip().lower()
    if normalized in _TRUTHY_VALUES:
        return True
    if normalized in _FALSY_VALUES:
        return False
    return None


def get_env_int(name: str, default: int) -> int:
    raw_value = get_env(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value.strip())
    except ValueError:
        return default


def get_env_float(name: str, default: float) -> float:
    raw_value = get_env(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value.strip())
    except ValueError:
        return default


def get_project_root() -> Path:
    return _PROJECT_ROOT


def resolve_project_settings_path() -> Path | None:
    from app.shared.infra.settings.support import PROJECT_SETTINGS_ENV_NAME

    configured = (get_env(PROJECT_SETTINGS_ENV_NAME) or "").strip()
    if not configured:
        return None
    path = Path(configured)
    if path.is_absolute():
        return path
    return _PROJECT_ROOT / path


def describe_project_settings_source() -> str:
    from app.shared.infra.settings.support import PROJECT_SETTINGS_SOURCE_LABEL

    path = resolve_project_settings_path()
    return str(path) if path is not None else PROJECT_SETTINGS_SOURCE_LABEL


__all__ = [
    "get_env",
    "get_env_bool",
    "get_env_choice",
    "get_env_float",
    "get_env_int",
    "get_env_list",
    "get_env_optional_bool",
    "get_project_root",
    "load_local_dotenv",
    "describe_project_settings_source",
    "resolve_project_settings_path",
    "set_runtime_env_overrides",
]
