"""Stable runtime filesystem paths for the backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import structlog

logger = structlog.get_logger()

_LEGACY_DB_NAME = "aiteachme.db"
_legacy_warning_emitted = False


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


def log_legacy_runtime_path_warnings() -> None:
    """Warn once when older runtime data paths are still present."""

    global _legacy_warning_emitted
    if _legacy_warning_emitted:
        return

    backend_root = get_backend_root()
    current_db_path = get_sqlite_db_path()
    legacy_candidates = [
        backend_root.parent / "data" / _LEGACY_DB_NAME,
        backend_root / "app" / "data" / _LEGACY_DB_NAME,
        backend_root / "app" / "shared" / "data" / _LEGACY_DB_NAME,
    ]

    for legacy_path in legacy_candidates:
        if legacy_path == current_db_path or not legacy_path.exists():
            continue
        logger.warning(
            "legacy_runtime_db_path_ignored",
            legacy_db_path=str(legacy_path),
            active_db_path=str(current_db_path),
        )

    _legacy_warning_emitted = True


__all__ = [
    "get_backend_root",
    "get_runtime_data_dir",
    "get_sqlite_db_path",
    "log_legacy_runtime_path_warnings",
]
