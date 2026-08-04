"""Fail-closed validation for the cloud runtime contract."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.shared.infra.env_support import get_env
from app.shared.infra.settings import get_project_settings

_MIN_AUTH_TOKEN_SECRET_LENGTH = 32
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_value(name: str) -> str:
    return (get_env(name) or "").strip()


def collect_project_settings_config_errors() -> list[str]:
    """Return project-settings schema errors without echoing configured values."""

    try:
        get_project_settings()
    except ValidationError as exc:
        errors: list[str] = []
        for detail in exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        ):
            location = ".".join(str(item) for item in detail.get("loc", ())) or "<root>"
            message = str(detail.get("msg") or "invalid value")
            errors.append(
                "project settings schema mismatch at "
                f"{location}: {message}; deploy a backend image compatible "
                "with the mounted PROJECT_SETTINGS_PATH"
            )
        return errors or [
            "project settings are incompatible with this backend build; "
            "deploy a matching backend image and PROJECT_SETTINGS_PATH"
        ]
    return []


def collect_cloud_runtime_config_errors() -> list[str]:
    """Return every cloud startup configuration error without exposing secrets."""

    errors = collect_project_settings_config_errors()

    if _env_value("APP_MODE").lower() != "cloud":
        errors.append("APP_MODE must be explicitly set to cloud")

    database_url = _env_value("DATABASE_URL")
    if not database_url:
        errors.append("DATABASE_URL must be configured for PostgreSQL")
    else:
        try:
            database_backend = make_url(database_url).get_backend_name()
        except (ArgumentError, ValueError):
            errors.append("DATABASE_URL must be a valid PostgreSQL URL")
        else:
            if database_backend != "postgresql":
                errors.append("DATABASE_URL must use PostgreSQL")

    if _env_value("STORAGE_BACKEND").lower() != "s3":
        errors.append("STORAGE_BACKEND must be explicitly set to s3")
    else:
        credential_mode = _env_value("S3_CREDENTIAL_MODE").lower() or "auto"
        if credential_mode == "auto":
            credential_mode = (
                "dogecloud_tmp_token"
                if _env_value("DOGECLOUD_API_ACCESS_KEY")
                and _env_value("DOGECLOUD_API_SECRET_KEY")
                else "static"
            )

        if credential_mode == "static":
            for name in ("S3_BUCKET", "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
                if not _env_value(name):
                    errors.append(f"{name} must be configured for static S3 storage")
        elif credential_mode == "dogecloud_tmp_token":
            if not (
                _env_value("DOGECLOUD_API_ACCESS_KEY")
                or _env_value("S3_ACCESS_KEY")
            ):
                errors.append(
                    "DOGECLOUD_API_ACCESS_KEY or S3_ACCESS_KEY must be configured "
                    "for DogeCloud S3 storage"
                )
            if not (
                _env_value("DOGECLOUD_API_SECRET_KEY")
                or _env_value("S3_SECRET_KEY")
            ):
                errors.append(
                    "DOGECLOUD_API_SECRET_KEY or S3_SECRET_KEY must be configured "
                    "for DogeCloud S3 storage"
                )
            if not (_env_value("DOGECLOUD_SPACE_NAME") or _env_value("S3_BUCKET")):
                errors.append(
                    "DOGECLOUD_SPACE_NAME or S3_BUCKET must be configured for DogeCloud S3 storage"
                )
        else:
            errors.append(
                "S3_CREDENTIAL_MODE must be static, dogecloud_tmp_token, or auto"
            )

    if _env_value("AUTH_ENABLED").lower() not in _TRUE_VALUES:
        errors.append("AUTH_ENABLED must be explicitly set to true")

    auth_token_secret = _env_value("AUTH_TOKEN_SECRET")
    if len(auth_token_secret) < _MIN_AUTH_TOKEN_SECRET_LENGTH:
        errors.append(
            "AUTH_TOKEN_SECRET must contain at least "
            f"{_MIN_AUTH_TOKEN_SECRET_LENGTH} characters"
        )

    return errors


__all__ = [
    "collect_cloud_runtime_config_errors",
    "collect_project_settings_config_errors",
]
