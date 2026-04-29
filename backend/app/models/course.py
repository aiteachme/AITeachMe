"""Course workspace model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class Course(SQLModel, table=True):
    """Course workspace root."""

    __tablename__ = "course"

    id: str = Field(primary_key=True)
    user_id: str = Field(default="local", foreign_key="user.id", index=True)
    name: str
    description: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    user_intent: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    normalized_name: str | None = Field(default=None, index=True)
    preferred_digest_mode: str | None = None
    preferred_digest_note: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    detected_discipline: str | None = None
    detected_sub_discipline: str | None = None
    profile_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False))
    settings_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False))
    learning_intent_text: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False))
    course_intro_text: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False))
    document_summary_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    llm_context_text: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False))
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    # ── 构建锁（云端模式下替代文件锁） ──
    build_lock_holder: str | None = Field(default=None)
    build_lock_at: datetime | None = Field(default=None)
