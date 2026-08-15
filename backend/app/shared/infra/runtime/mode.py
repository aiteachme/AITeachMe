"""Runtime mode and app-level environment helpers."""

from __future__ import annotations

from functools import lru_cache
from importlib import metadata
from pathlib import Path
import sys
import tomllib

from app.shared.infra.env_support import get_env, get_env_optional_bool

_BACKEND_DISTRIBUTION_NAME = "aiteachme-backend"
_UNKNOWN_APP_VERSION = "0.0.0"


def _read_pyproject_version() -> str | None:
    roots: list[Path] = []
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        roots.append(Path(str(bundled_root)).resolve())

    current_path = Path(__file__).resolve()
    roots.extend(current_path.parents)

    for root in roots:
        pyproject_path = root / "pyproject.toml"
        if not pyproject_path.is_file():
            continue

        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = data.get("project")
        if not isinstance(project, dict):
            continue

        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()

    return None


def _read_distribution_version() -> str | None:
    try:
        return metadata.version(_BACKEND_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return None


@lru_cache(maxsize=1)
def get_app_version() -> str:
    return _read_pyproject_version() or _read_distribution_version() or _UNKNOWN_APP_VERSION


APP_VERSION = get_app_version()


def resolve_app_mode() -> str:
    raw_value = (get_env("APP_MODE") or "").strip().lower()
    if not raw_value:
        return "local"
    if raw_value in {"local", "cloud"}:
        return raw_value
    raise ValueError("APP_MODE must be either 'local' or 'cloud'.")


def is_cloud_mode() -> bool:
    return resolve_app_mode() == "cloud"


def is_local_mode() -> bool:
    return not is_cloud_mode()


def resolve_auth_enabled() -> bool:
    explicit_value = get_env_optional_bool("AUTH_ENABLED")
    if explicit_value is not None:
        return explicit_value
    return is_cloud_mode()


def resolve_credits_enabled() -> bool:
    explicit_value = get_env_optional_bool("CREDITS_ENABLED")
    return False if explicit_value is None else explicit_value


def get_guest_cookie_name() -> str:
    return (get_env("GUEST_COOKIE_NAME", "atm_guest_token") or "atm_guest_token").strip() or "atm_guest_token"


def resolve_guest_cookie_samesite() -> str:
    raw_value = (get_env("GUEST_COOKIE_SAMESITE", "auto") or "auto").strip().lower()
    if raw_value in {"lax", "strict", "none"}:
        return raw_value
    return "none" if is_cloud_mode() else "lax"


def resolve_guest_cookie_secure() -> bool:
    explicit_value = get_env_optional_bool("GUEST_COOKIE_SECURE")
    if explicit_value is not None:
        return explicit_value
    return is_cloud_mode() or resolve_guest_cookie_samesite() == "none"


__all__ = [
    "APP_VERSION",
    "get_app_version",
    "get_guest_cookie_name",
    "is_cloud_mode",
    "is_local_mode",
    "resolve_auth_enabled",
    "resolve_credits_enabled",
    "resolve_app_mode",
    "resolve_guest_cookie_samesite",
    "resolve_guest_cookie_secure",
]
