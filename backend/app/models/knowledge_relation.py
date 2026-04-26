"""Knowledge graph relation models."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.models.enums import KnowledgeRelationStatus
from app.utils.time import utcnow


class KnowledgeEdge(SQLModel, table=True):
    """Directed relation between two knowledge units."""

    __tablename__ = "knowledge_edge"
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_edge_subject_src_tgt_type",
        ),
        Index("ix_edge_subject_status", "subject", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    source_node_id: int = Field(foreign_key="knowledge_unit.id", index=True)
    target_node_id: int = Field(foreign_key="knowledge_unit.id", index=True)
    edge_type: str = Field(index=True)
    description: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    evidence_refs_json: str = Field(default="[]", sa_column=sa.Column(sa.Text(), nullable=False, default="[]"))
    weight: float = Field(default=1.0)
    confidence: float = Field(default=0.5)
    status: str = Field(default=KnowledgeRelationStatus.PENDING.value)
    build_revision_no: int = Field(default=0, index=True)
    current_revision_id: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EdgeRevision(SQLModel):
    """Materialized revision view derived from the current relation body."""

    id: int | None = None
    edge_id: int
    revision_no: int
    description: str
    weight: float
    confidence: float
    revision_reason: str
    is_current: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class EvidenceLink(SQLModel):
    """Structured evidence payload embedded on a knowledge unit or relation."""

    id: int | None = None
    subject: str = ""
    entity_type: str
    entity_id: int
    entity_revision_id: int | None = Field(default=None)
    document_id: int
    chunk_id: int
    quote_text: str = ""
    source_span_start: int | None = Field(default=None)
    source_span_end: int | None = Field(default=None)
    evidence_role: str
    extraction_method: str = Field(default="llm")
    field_scope: str = Field(default="summary")
    confidence: float = Field(default=1.0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
