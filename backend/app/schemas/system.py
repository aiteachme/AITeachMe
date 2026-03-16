"""Schemas for runtime mode discovery."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InitRequest(BaseModel):
    """Empty request body for the system init endpoint."""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class RuntimeUser(BaseModel):
    """Minimal user context surfaced to the frontend."""

    user_id: str = Field(description="Stable user identifier.", examples=["local"])
    email: str | None = Field(default=None, description="User email when available.")
    is_local: bool = Field(description="Whether the current user is the built-in local placeholder.")


class InitResponse(BaseModel):
    """Runtime metadata the frontend can use before rendering subject-specific pages."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "mode": "local",
                "auth_enabled": False,
                "auth_ready": False,
                "current_user": {"user_id": "local", "email": None, "is_local": True},
                "feature_flags": {
                    "auth": False,
                    "files": True,
                    "knowledge": True,
                    "chat": True,
                    "exam": True,
                    "profile": True,
                },
                "version": "0.2.0",
            }
        }
    )

    mode: str = Field(description="Current backend runtime mode.", examples=["local"])
    auth_enabled: bool = Field(description="Whether auth is enabled by configuration.")
    auth_ready: bool = Field(description="Whether auth is fully implemented and usable.")
    current_user: RuntimeUser | None = Field(default=None, description="Current runtime user context.")
    feature_flags: dict[str, bool] = Field(description="Feature availability flags for the frontend.")
    version: str = Field(description="Backend version string.")
