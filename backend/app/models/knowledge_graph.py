"""Knowledge graph models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class KnowledgeNode(SQLModel, table=True):
    """Knowledge node with flattened body content."""

    __tablename__ = "knowledge_node"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "node_type",
            "normalized_name",
            name="uq_knowledge_node_subject_name",
        ),
        Index("ix_knowledge_node_subject_status", "subject_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    node_type: str = Field(index=True)
    canonical_name: str
    normalized_name: str = Field(index=True)
    summary: str = Field(default="")
    body: str = Field(default="")
    status: str = Field(default="active", index=True)
    confidence: float = Field(default=1.0)
    merged_into_node_id: int | None = Field(default=None, foreign_key="knowledge_node.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeAlias(SQLModel, table=True):
    """Node alias table."""

    __tablename__ = "knowledge_alias"
    __table_args__ = (
        UniqueConstraint("node_id", "normalized_alias", name="uq_knowledge_alias"),
    )

    id: int | None = Field(default=None, primary_key=True)
    node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    alias: str
    normalized_alias: str = Field(index=True)
    language: str = Field(default="zh")
    source: str = Field(default="llm")
    confidence: float = Field(default=1.0)
    is_primary: bool = Field(default=False)
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=utcnow)


class KnowledgeEdge(SQLModel, table=True):
    """Directed knowledge relation."""

    __tablename__ = "knowledge_edge"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "source_node_id",
            "target_node_id",
            "edge_type",
            name="uq_knowledge_edge_subject_pair",
        ),
        Index("ix_knowledge_edge_subject_status", "subject_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    source_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    target_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    edge_type: str = Field(index=True)
    description: str = Field(default="")
    weight: float = Field(default=1.0)
    confidence: float = Field(default=1.0)
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeEvidence(SQLModel, table=True):
    """Node or edge evidence backed by retrieval chunks."""

    __tablename__ = "knowledge_evidence"
    __table_args__ = (
        Index("ix_knowledge_evidence_node", "node_id", "is_active"),
        Index("ix_knowledge_evidence_edge", "edge_id", "is_active"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    node_id: int | None = Field(default=None, foreign_key="knowledge_node.id", index=True)
    edge_id: int | None = Field(default=None, foreign_key="knowledge_edge.id", index=True)
    retrieval_chunk_id: int = Field(foreign_key="retrieval_chunk.id", index=True)
    quote_text: str = Field(default="")
    source_span_start: int | None = Field(default=None, ge=0)
    source_span_end: int | None = Field(default=None, ge=0)
    evidence_role: str = Field(default="support")
    extraction_method: str = Field(default="llm")
    field_scope: str = Field(default="body")
    confidence: float = Field(default=1.0)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
