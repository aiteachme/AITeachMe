"""知识构建相关模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.enums import TaskStatus


class DocSet(SQLModel, table=True):
    """一次知识构建产出的知识集合。"""

    __tablename__ = "doc_set"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    title: str
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocBuildJob(SQLModel, table=True):
    """知识构建任务记录。"""

    __tablename__ = "doc_build_job"

    id: int | None = Field(default=None, primary_key=True)
    doc_set_id: int = Field(foreign_key="doc_set.id", index=True)
    status: str = Field(default=TaskStatus.PENDING.value, index=True)
    progress: int = 0
    current_step: str | None = Field(default=None)
    message: str = ""
    error_message: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DocSetSourceFile(SQLModel, table=True):
    """知识集合与源文件的关联表。"""

    __tablename__ = "doc_set_source_file"
    __table_args__ = (UniqueConstraint("doc_set_id", "raw_file_id"),)

    id: int | None = Field(default=None, primary_key=True)
    doc_set_id: int = Field(foreign_key="doc_set.id", index=True)
    raw_file_id: int = Field(foreign_key="raw_file.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Document(SQLModel, table=True):
    """知识集合中的单篇文档。"""

    __tablename__ = "document"

    id: int | None = Field(default=None, primary_key=True)
    doc_set_id: int = Field(foreign_key="doc_set.id", index=True)
    subject: str = Field(index=True)
    source_file_id: int = Field(foreign_key="raw_file.id", index=True)
    title: str
    markdown_content: str = ""
    current_step: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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


class DocumentOutlineNode(SQLModel, table=True):
    """文档大纲节点。"""

    __tablename__ = "document_outline_node"

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    parent_id: int | None = Field(default=None, foreign_key="document_outline_node.id")
    title: str
    level: int
    order_index: int
