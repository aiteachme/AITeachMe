"""Knowledge graph sync provenance models."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, Index, SQLModel

from app.utils.time import utcnow


class KnowledgeGraphSyncRun(SQLModel, table=True):
    """One persisted knowledge-graph synchronization pass."""

    __tablename__ = "knowledge_graph_sync_run"
    __table_args__ = (
        Index("ix_kg_sync_run_subject_revision", "subject_id", "graph_revision_no"),
        Index("ix_kg_sync_run_subject_doc_version", "subject_id", "doc_version_no"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject_id: str = Field(foreign_key="subject.id", index=True)
    build_session_id: str | None = Field(default=None, index=True)
    doc_version_no: int = Field(default=0, index=True)
    graph_revision_no: int = Field(default=0, index=True)
    status: str = Field(default="running", index=True)
    metrics_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    error_message: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeGraphSourceRef(SQLModel, table=True):
    """Structured source reference for a graph unit or edge."""

    __tablename__ = "knowledge_graph_source_ref"
    __table_args__ = (
        Index("ix_kg_source_ref_entity", "entity_type", "entity_id"),
        Index("ix_kg_source_ref_subject_chapter", "subject_id", "chapter_index"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject_id: str = Field(foreign_key="subject.id", index=True)
    entity_type: str = Field(index=True)
    entity_id: int = Field(index=True)
    sync_run_id: int | None = Field(default=None, foreign_key="knowledge_graph_sync_run.id", index=True)
    knowledge_document_id: int | None = Field(default=None, foreign_key="knowledge_document.id", index=True)
    chapter_index: int = Field(default=0, index=True)
    anchor: str = Field(default="", index=True)
    source_kind: str = Field(default="", index=True)
    source_file_ids_json: str = Field(default="[]", sa_column=sa.Column(sa.Text(), nullable=False, default="[]"))
    quote_text: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    confidence: float = Field(default=1.0)
    created_at: datetime = Field(default_factory=utcnow)
