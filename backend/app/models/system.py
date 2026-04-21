"""System-level runtime models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemSettingsSnapshot(SQLModel, table=True):
    """Current non-secret project settings snapshot."""

    __tablename__ = "system_settings_snapshot"

    id: str = Field(primary_key=True)
    settings_path: str = Field(default="")
    settings_hash: str = Field(default="", index=True)
    settings_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SystemRuntimeSettings(SQLModel, table=True):
    """Global non-secret runtime settings overrides."""

    __tablename__ = "system_runtime_settings"

    id: str = Field(primary_key=True)
    settings_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserRuntimeSettings(SQLModel, table=True):
    """Per-user non-secret runtime settings overrides."""

    __tablename__ = "user_runtime_settings"

    user_id: str = Field(primary_key=True, foreign_key="user.id")
    settings_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
