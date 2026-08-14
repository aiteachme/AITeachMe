"""课程分享导入回执模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class CourseShareImport(SQLModel, table=True):
    """记录一个用户对同一分享的唯一导入结果。"""

    __tablename__ = "course_share_import"
    __table_args__ = (
        sa.UniqueConstraint(
            "share_id",
            "user_id",
            name="uq_course_share_import_share_user",
        ),
    )

    id: str = Field(
        default_factory=lambda: f"share_import_{uuid4().hex}",
        primary_key=True,
    )
    share_id: str = Field(foreign_key="course_share.id")
    user_id: str = Field(foreign_key="user.id", index=True)
    imported_course_id: str = Field(index=True)
    result_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(sa.JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
