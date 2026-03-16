"""学科模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class Subject(SQLModel, table=True):
    """学科空间。"""

    __tablename__ = "subject"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
