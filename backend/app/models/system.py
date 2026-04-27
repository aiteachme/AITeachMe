"""System-level runtime models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemRuntimeSettings(SQLModel, table=True):
    """Global runtime settings overrides and effective settings snapshot."""

    __tablename__ = "system_runtime_settings"

    id: str = Field(primary_key=True)
    settings_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    settings_source: str = Field(default="")
    settings_hash: str = Field(default="", index=True)
    effective_settings_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
