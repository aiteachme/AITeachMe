"""Retrieval chunk models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class RetrievalChunk(SQLModel, table=True):
    """Unified retrieval, citation, and embedding chunk."""

    __tablename__ = "retrieval_chunk"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "chunk_role",
            "chunk_index",
            name="uq_retrieval_chunk_source_index",
        ),
        UniqueConstraint("digest_chunk_uid", name="uq_retrieval_chunk_digest_uid"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    source_type: str = Field(index=True)
    source_id: int = Field(index=True)
    chunk_role: str = Field(default="body", index=True)
    chunk_index: int = Field(default=0, ge=0)
    level: int = Field(default=0, ge=0)
    title: str = Field(default="")
    header_path: str = Field(default="")
    digest_chunk_uid: str = Field(index=True)
    build_session_id: str | None = Field(default=None, index=True)
    content: str
    token_count: int = Field(default=0, ge=0)
    page_num: int | None = Field(default=None, ge=1)
    metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
