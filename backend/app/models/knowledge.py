"""知识构建相关模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class Document(SQLModel, table=True):
    """知识集合中的单篇文档。"""

    __tablename__ = "document"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    source_file_id: int = Field(foreign_key="raw_file.id", index=True)
    title: str
    markdown_content: str = ""
    current_step: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DocumentChunk(SQLModel, table=True):
    """文档切块。"""

    __tablename__ = "document_chunk"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    title: str
    level: int
    header_path: str
    chunk_index: int
    content: str



