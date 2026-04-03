"""Shared runtime path entrypoint.

This module currently proxies the legacy runtime-path helpers.
"""

from __future__ import annotations

from app.infra.runtime_paths import get_runtime_data_dir, get_sqlite_db_path, log_legacy_runtime_path_warnings

__all__ = ["get_runtime_data_dir", "get_sqlite_db_path", "log_legacy_runtime_path_warnings"]

