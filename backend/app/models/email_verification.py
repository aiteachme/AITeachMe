"""Email confirmation model."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class EmailVerificationCode(SQLModel, table=True):
    """One-time email confirmation record."""

    __tablename__ = "email_confirmation"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    purpose: str = Field(default="register", index=True)
    code_hash: str = Field(index=True)
    expires_at: datetime = Field(index=True)
    consumed_at: datetime | None = Field(default=None, index=True)
    attempt_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
