"""Runtime mode and app-level environment helpers."""

from __future__ import annotations

import os

from app.shared.infra.env_support import get_env, get_env_optional_bool

APP_VERSION = "0.0.1"


def resolve_app_mode() -> str:
    raw_value = (get_env("APP_MODE", "auto") or "auto").strip().lower()
    if raw_value in {"local", "cloud"}:
        return raw_value
    if os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL"):
        return "cloud"
    return "local"


def is_cloud_mode() -> bool:
    return resolve_app_mode() == "cloud"


def is_local_mode() -> bool:
    return not is_cloud_mode()


def resolve_auth_enabled() -> bool:
    explicit_value = get_env_optional_bool("AUTH_ENABLED")
    if explicit_value is not None:
        return explicit_value
    return is_cloud_mode()


def get_app_version() -> str:
    return APP_VERSION


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
    "resolve_app_mode",
    "resolve_guest_cookie_samesite",
    "resolve_guest_cookie_secure",
]
