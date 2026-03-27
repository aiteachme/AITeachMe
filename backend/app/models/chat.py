"""Chat models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

from app.utils.time import utcnow


class ChatMessage(SQLModel, table=True):
    """Chat message."""

    __tablename__ = "chat_message"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    session_id: str = Field(foreign_key="chat_session.id", index=True)
    turn_id: str = Field(index=True)
    source: str | None = Field(default=None, index=True)
    anchor_id: str | None = Field(default=None, index=True)
    selected_text: str | None = Field(default=None)
    source_chunk_id: int | None = Field(default=None, foreign_key="retrieval_chunk.id", index=True)
    role: str
    content: str
    contexts_json: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    meta_json: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class ChatSession(SQLModel, table=True):
    """Chat session."""

    __tablename__ = "chat_session"

    id: str = Field(primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    title: str = Field(default="New Chat")
    source: str | None = Field(default=None, index=True)
    meta_json: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
    last_message_at: datetime = Field(default_factory=utcnow, index=True)
