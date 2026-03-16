"""聊天记录模型定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel


class ChatMessage(SQLModel, table=True):
    """聊天消息。"""

    __tablename__ = "chat_message"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    turn_id: str = Field(index=True)
    role: str
    content: str
    contexts: Any | None = Field(default=None, sa_column=Column(sa.JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
