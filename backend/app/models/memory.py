"""Database-portable memory and learning-log models."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class MemoryRecord(SQLModel, table=True):
    __tablename__ = "memory_entries"
    __table_args__ = (
        sa.UniqueConstraint("key", name="uq_memory_entries_key"),
        sa.Index("ix_memory_entries_user_tag", "user_id", "tag"),
    )

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True)
    user_id: str = Field(default="default", index=True)
    content: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    tag: str = "general"
    importance: float = 0.5
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class LearningLogRecord(SQLModel, table=True):
    __tablename__ = "learning_logs"
    __table_args__ = (
        sa.Index("ix_learning_logs_user_created", "user_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="default", index=True)
    event_type: str = Field(index=True)
    course_id: str = ""
    summary: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    metadata_json: dict = Field(
        default_factory=dict,
        sa_column=sa.Column("metadata", sa.JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)
