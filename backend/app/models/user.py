"""User ownership model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class User(SQLModel, table=True):
    """Top-level user record."""

    __tablename__ = "user"

    id: str = Field(primary_key=True)
    username: str = Field(index=True, unique=True)
    email: str | None = Field(default=None, index=True, unique=True)
    device_key: str | None = Field(default=None, index=True, unique=True)
    password_hash: str | None = Field(default=None)
    is_registered: bool = Field(default=False, index=True)
    role: str = Field(default="user", index=True)
    display_name: str | None = Field(default=None)
    avatar_url: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    email_verified_at: datetime | None = Field(default=None, index=True)
    merged_into_user_id: str | None = Field(
        default=None,
        foreign_key="user.id",
        index=True,
    )
    last_seen_ip: str | None = None
    profile_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False))
    runtime_settings_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
