"""Retrieval chunk model."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class RetrievalChunk(SQLModel, table=True):
    """Canonical retrieval chunk derived from one raw file."""

    __tablename__ = "retrieval_chunk"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_retrieval_chunk_document_id_chunk_index",
        ),
        UniqueConstraint(
            "subject",
            "digest_chunk_uid",
            name="uq_retrieval_chunk_subject_digest_chunk_uid",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(foreign_key="subject.slug", index=True)
    document_id: int = Field(foreign_key="raw_file.id", index=True)
    title: str
    level: int
    header_path: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    chunk_index: int
    digest_chunk_uid: str = Field(default="", index=True)
    build_session_id: str = Field(default="", index=True)
    content: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    embedding_model: str | None = None
    vector_ref: str | None = None
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


DocumentChunk = RetrievalChunk
