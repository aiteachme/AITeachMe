"""Knowledge document source models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class Document(SQLModel, table=True):
    """A source document materialized for digest processing."""

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
    """A canonical digest chunk derived from one shared section packet."""

    __tablename__ = "document_chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        UniqueConstraint("document_id", "digest_chunk_uid"),
    )

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id", index=True)
    title: str
    level: int
    header_path: str
    chunk_index: int
    digest_chunk_uid: str = Field(index=True)
    build_session_id: str = Field(index=True)
    content: str
