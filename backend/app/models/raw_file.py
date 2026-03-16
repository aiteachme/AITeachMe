"""原始文件模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.enums import TaskStatus


class RawFile(SQLModel, table=True):
    """用户上传的原始资料文件。"""

    __tablename__ = "raw_file"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    filename: str
    filetype: str
    file_path: str
    markdown_path: str | None = None
    asset_dir: str | None = None
    status: str = Field(default=TaskStatus.PENDING.value, index=True)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
