"""User ownership model."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class User(SQLModel, table=True):
    """Top-level user record."""

    __tablename__ = "user"

    id: str = Field(primary_key=True)
    username: str = Field(index=True, unique=True)
    email: str | None = Field(default=None, index=True)
    last_seen_ip: str | None = None
    profile_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
