"""学习画像模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class UserProfile(SQLModel, table=True):
    """知识点掌握度记录。"""

    __tablename__ = "user_profile"

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    knowledge_point: str = Field(index=True)
    mastery: float | None = None
    attempts: int = 0
    correct: int = 0
    updated_at: datetime = Field(default_factory=datetime.utcnow)
