"""Schemas for auth scaffolding endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.system import RuntimeUser


class RegisterRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "user@example.com", "password": "change-me"}}
    )

    email: str = Field(description="Email address placeholder for the future auth flow.")
    password: str = Field(min_length=6, description="Plaintext password placeholder for the future auth flow.")


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "user@example.com", "password": "change-me"}}
    )

    email: str = Field(description="Email address placeholder for the future auth flow.")
    password: str = Field(min_length=6, description="Plaintext password placeholder for the future auth flow.")


class LogoutRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {}})


class AuthSessionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "auth_enabled": False,
                "auth_ready": False,
                "token_type": "bearer",
                "access_token": None,
                "current_user": {"user_id": "local", "email": None, "is_local": True},
            }
        }
    )

    auth_enabled: bool
    auth_ready: bool
    token_type: str = "bearer"
    access_token: str | None = None
    current_user: RuntimeUser | None = None
