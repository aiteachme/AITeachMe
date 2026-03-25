"""Knowledge document models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class KnowledgeDocument(SQLModel, table=True):
    """Published knowledge document chapter or section."""

    __tablename__ = "knowledge_document"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "doc_type",
            "chapter_index",
            "version_no",
            name="uq_knowledge_document_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    doc_type: str = Field(default="chapter", index=True)
    chapter_index: int = Field(default=1, ge=1)
    title: str
    summary: str = Field(default="")
    content_markdown: str = Field(default="")
    storage_backend: str = Field(default="local")
    storage_key: str | None = Field(default=None)
    tags_json: str = Field(default="[]")
    source_raw_file_ids_json: str = Field(default="[]")
    word_count: int = Field(default=0, ge=0)
    version_no: int = Field(default=1, ge=1)
    status: str = Field(default="published", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
