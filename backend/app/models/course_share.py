"""课程分享快照模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class CourseShare(SQLModel, table=True):
    """一个可撤销、可过期的课程分享快照。"""

    __tablename__ = "course_share"

    id: str = Field(primary_key=True)
    owner_user_id: str = Field(default="local", foreign_key="user.id", index=True)
    source_course_id: str = Field(index=True)
    token: str = Field(sa_column=sa.Column(sa.String(length=160), nullable=False, unique=True, index=True))
    token_hash: str = Field(sa_column=sa.Column(sa.String(length=64), nullable=False, unique=True, index=True))
    storage_key: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    course_name: str = Field(default="", index=True)
    course_description: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    course_icon_key: str | None = Field(default=None)
    file_size_bytes: int = Field(default=0)
    content_sha256: str = Field(default="", sa_column=sa.Column(sa.String(length=64), nullable=False, default=""))
    options_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    stats_json: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
    status: str = Field(default="active", index=True)
    import_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(index=True)
    revoked_at: datetime | None = Field(default=None, index=True)
    last_imported_at: datetime | None = Field(default=None)
