"""Knowledge graph models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class KnowledgeNode(SQLModel, table=True):
    """Canonical knowledge node."""

    __tablename__ = "knowledge_node"
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "node_type",
            "normalized_name",
            name="uq_node_subject_type_name",
        ),
        Index("ix_node_subject_status", "subject", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    node_type: str = Field(index=True)
    canonical_name: str
    normalized_name: str = Field(index=True)
    summary: str = ""
    body: str = ""
    body_markdown: str = ""
    aliases_json: str = Field(default="[]")
    evidence_refs_json: str = Field(default="[]")
    status: str = Field(default="pending")
    confidence: float = Field(default=1.0)
    build_revision_no: int = Field(default=0, index=True)
    current_revision_id: int | None = Field(default=None)
    merged_into_node_id: int | None = Field(default=None, foreign_key="knowledge_node.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeAlias(SQLModel):
    """Structured alias payload embedded on a knowledge node."""

    id: int | None = None
    node_id: int
    alias: str
    normalized_alias: str
    language: str = Field(default="zh")
    source: str = Field(default="llm")
    confidence: float = Field(default=1.0)
    is_primary: bool = Field(default=False)
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=utcnow)


class KnowledgeEdge(SQLModel, table=True):
    """Directed relation between two knowledge nodes."""

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
    source_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    target_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    edge_type: str = Field(index=True)
    description: str = ""
    evidence_refs_json: str = Field(default="[]")
    weight: float = Field(default=1.0)
    confidence: float = Field(default=0.5)
    status: str = Field(default="pending")
    build_revision_no: int = Field(default=0, index=True)
    current_revision_id: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeRevision(SQLModel):
    """Materialized revision view derived from the current node body."""

    id: int | None = None
    node_id: int
    revision_no: int
    title: str
    summary: str = ""
    body: str = ""
    revision_reason: str
    is_current: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class EdgeRevision(SQLModel):
    """Materialized revision view derived from the current edge body."""

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
    """Structured evidence payload embedded on a node or edge."""

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
