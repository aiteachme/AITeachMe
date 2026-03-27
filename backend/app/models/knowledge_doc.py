"""Knowledge document models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class KnowledgeDocument(SQLModel, table=True):
    """Digest-generated published knowledge document."""

    __tablename__ = "knowledge_document"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    root_document_id: int | None = Field(default=None, foreign_key="knowledge_document.id", index=True)
    parent_document_id: int | None = Field(default=None, foreign_key="knowledge_document.id", index=True)
    package_key: str | None = Field(default=None, index=True)
    build_session_id: str | None = Field(default=None, index=True)
    chapter_index: int
    order_index: int = Field(default=0)
    title: str
    summary: str = ""
    markdown_content: str = ""
    content_markdown: str = ""
    markdown_path: str | None = None
    markdown_uri: str | None = None
    tags: str = Field(default="[]")
    source_file_ids: str = Field(default="[]")
    word_count: int = Field(default=0)
    version: int = Field(default=1)
    version_no: int = Field(default=1)
    document_role: str = Field(default="chapter", index=True)
    digest_mode: str | None = Field(default=None, index=True)
    mode_confidence: float | None = Field(default=None)
    mode_decision_json: str = Field(default="{}")
    manifest_json: str = Field(default="{}")
    source_scope_json: str = Field(default="{}")
    build_kind: str = Field(default="full")
    is_current: bool = Field(default=True, index=True)
    status: str = Field(default="draft", index=True)
    published_at: datetime | None = Field(default=None)
    superseded_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


KnowledgeDoc = KnowledgeDocument
