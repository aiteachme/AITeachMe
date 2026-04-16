"""Stable runtime filesystem paths for the backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_LEGACY_DB_NAME = "aiteachme.db"


@lru_cache(maxsize=1)
def get_backend_root() -> Path:
    """Return the repository-local backend root directory."""

    return Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
def get_runtime_data_dir() -> Path:
    """Return the fixed runtime data directory used by local backend runs."""

    data_dir = get_backend_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_sqlite_db_path() -> Path:
    """Return the fixed sqlite database path for the local backend."""

    return get_runtime_data_dir() / _LEGACY_DB_NAME


__all__ = [
    "get_backend_root",
    "get_runtime_data_dir",
    "get_sqlite_db_path",
]
