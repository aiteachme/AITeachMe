"""Small helpers for loading and parsing environment variables.

This module does not model environment variables as one global settings object.
It only:
1. loads repo-local `.env` into `os.environ`
2. provides a few typed parsing helpers
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
_DOTENV_CANDIDATES = (
    _PROJECT_ROOT / ".env",
    _BACKEND_ROOT / ".env",
)
_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_FALSY_VALUES = {"0", "false", "no", "off"}
_ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


@lru_cache(maxsize=1)
def load_local_dotenv() -> None:
    """Load repo-local `.env` values into `os.environ` if they are unset."""

    for path in _DOTENV_CANDIDATES:
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


def resolve_writable_local_env_path() -> Path:
    for path in _DOTENV_CANDIDATES:
        if path.exists():
            return path
    return _PROJECT_ROOT / ".env"


def write_local_env_updates(updates: Mapping[str, str | None]) -> Path:
    path = resolve_writable_local_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        existing_lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        existing_lines = []

    pending = {key: (None if value is None else str(value)) for key, value in updates.items()}
    new_lines: list[str] = []

    for line in existing_lines:
        match = _ENV_LINE_RE.match(line)
        if not match:
            new_lines.append(line)
            continue

        env_key = match.group(1)
        if env_key not in pending:
            new_lines.append(line)
            continue

        value = pending.pop(env_key)
        if value is None or not value.strip():
            continue
        new_lines.append(f"{env_key}={value}")

    for env_key, value in pending.items():
        if value is None or not value.strip():
            continue
        new_lines.append(f"{env_key}={value}")

    content = "\n".join(new_lines).rstrip()
    path.write_text(f"{content}\n" if content else "", encoding="utf-8")

    load_local_dotenv.cache_clear()
    for env_key, value in updates.items():
        if value is None or not str(value).strip():
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = str(value)

    return path


__all__ = [
    "get_env",
    "get_env_bool",
    "get_env_float",
    "get_env_int",
    "get_env_optional_bool",
    "get_project_root",
    "load_local_dotenv",
    "describe_project_settings_source",
    "resolve_project_settings_path",
    "resolve_writable_local_env_path",
    "write_local_env_updates",
]
