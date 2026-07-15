"""Canonical runtime helpers for app mode, local paths, and background tasks."""

from app.shared.infra.runtime.cloud_config import collect_cloud_runtime_config_errors
from app.shared.infra.runtime.mode import (
    get_app_version,
    get_guest_cookie_name,
    is_cloud_mode,
    is_local_mode,
    resolve_auth_enabled,
    resolve_app_mode,
    resolve_guest_cookie_samesite,
    resolve_guest_cookie_secure,
)
from app.shared.infra.runtime.paths import (
    get_backend_root,
    get_runtime_data_dir,
    get_sqlite_db_path,
)
from app.shared.infra.runtime.tasks import BackgroundTaskRegistry, ManagedTaskRecord

__all__ = [
    "BackgroundTaskRegistry",
    "ManagedTaskRecord",
    "collect_cloud_runtime_config_errors",
    "get_app_version",
    "get_backend_root",
    "get_guest_cookie_name",
    "get_runtime_data_dir",
    "get_sqlite_db_path",
    "is_cloud_mode",
    "is_local_mode",
    "resolve_auth_enabled",
    "resolve_app_mode",
    "resolve_guest_cookie_samesite",
    "resolve_guest_cookie_secure",
]
