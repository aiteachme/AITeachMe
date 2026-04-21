"""Storage-related environment helpers."""

from __future__ import annotations

from app.shared.infra.env_support import get_env


def get_storage_backend() -> str:
    explicit = (get_env("STORAGE_BACKEND", "auto") or "auto").strip().lower() or "auto"
    if explicit in {"local", "s3"}:
        return explicit
    if (get_env("S3_BUCKET") or "").strip() and (get_env("S3_ENDPOINT") or "").strip():
        return "s3"
    return "local"


def storage_is_s3() -> bool:
    return get_storage_backend() == "s3"


def resolve_s3_addressing_style() -> str:
    value = (get_env("S3_ADDRESSING_STYLE", "virtual") or "virtual").strip().lower()
    if value in {"auto", "virtual", "path"}:
        return value
    return "virtual"


def resolve_s3_credential_mode() -> str:
    value = (get_env("S3_CREDENTIAL_MODE", "auto") or "auto").strip().lower()
    if value in {"static", "dogecloud_tmp_token"}:
        return value
    if get_env("DOGECLOUD_API_ACCESS_KEY") and get_env("DOGECLOUD_API_SECRET_KEY"):
        return "dogecloud_tmp_token"
    return "static"


def s3_uses_dogecloud_tmp_token() -> bool:
    return resolve_s3_credential_mode() == "dogecloud_tmp_token"


def resolve_dogecloud_api_access_key() -> str | None:
    value = get_env("DOGECLOUD_API_ACCESS_KEY")
    if value:
        return value
    if s3_uses_dogecloud_tmp_token():
        return get_env("S3_ACCESS_KEY")
    return None


def resolve_dogecloud_api_secret_key() -> str | None:
    value = get_env("DOGECLOUD_API_SECRET_KEY")
    if value:
        return value
    if s3_uses_dogecloud_tmp_token():
        return get_env("S3_SECRET_KEY")
    return None


def resolve_dogecloud_space_name() -> str | None:
    value = get_env("DOGECLOUD_SPACE_NAME")
    if value:
        return value
    return get_env("S3_BUCKET")


__all__ = [
    "get_storage_backend",
    "resolve_dogecloud_api_access_key",
    "resolve_dogecloud_api_secret_key",
    "resolve_dogecloud_space_name",
    "resolve_s3_addressing_style",
    "resolve_s3_credential_mode",
    "s3_uses_dogecloud_tmp_token",
    "storage_is_s3",
]
