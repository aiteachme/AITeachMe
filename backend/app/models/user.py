"""User models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class User(SQLModel, table=True):
    """Runtime user record."""

    __tablename__ = "user"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    last_used_ip: str | None = Field(default=None)
    email: str | None = Field(default=None, index=True)
    profile_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
