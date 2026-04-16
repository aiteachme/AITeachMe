"""Small helpers for loading and parsing environment variables.

This module does not model environment variables as one global settings object.
It only:
1. loads repo-local `.env` into `os.environ`
2. provides a few typed parsing helpers
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
_DOTENV_CANDIDATES = (
    _PROJECT_ROOT / ".env",
    _BACKEND_ROOT / ".env",
)
_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_FALSY_VALUES = {"0", "false", "no", "off"}


@lru_cache(maxsize=1)
def load_local_dotenv() -> None:
    """Load repo-local `.env` values into `os.environ` if they are unset."""

    for path in _DOTENV_CANDIDATES:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, raw_value = line.partition("=")
            env_key = key.strip()
            if not env_key or env_key in os.environ:
                continue
            value = raw_value.strip().strip('"').strip("'")
            os.environ[env_key] = value


def get_env(name: str, default: str | None = None) -> str | None:
    load_local_dotenv()
    value = os.getenv(name)
    if value is None:
        return default
    return value


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


def resolve_project_settings_path() -> Path:
    configured = (get_env("PROJECT_SETTINGS_PATH") or "").strip()
    if not configured:
        configured = "settings.yaml"
    path = Path(configured)
    if path.is_absolute():
        return path
    return _PROJECT_ROOT / path


__all__ = [
    "get_env",
    "get_env_bool",
    "get_env_float",
    "get_env_int",
    "get_env_optional_bool",
    "get_project_root",
    "load_local_dotenv",
    "resolve_project_settings_path",
]
