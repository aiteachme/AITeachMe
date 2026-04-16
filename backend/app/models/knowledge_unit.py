"""KnowledgeUnit domain models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.models.enums import KnowledgeUnitStatus, KnowledgeUnitTypeSource
from app.utils.time import utcnow


class KnowledgeUnit(SQLModel, table=True):
    """Canonical knowledge unit."""

    __tablename__ = "knowledge_unit"
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "node_type",
            "normalized_name",
            name="uq_unit_subject_type_name",
        ),
        Index("ix_unit_subject_status", "subject", "status"),
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
    status: str = Field(default=KnowledgeUnitStatus.PENDING.value)
    confidence: float = Field(default=1.0)
    type_confidence: float = Field(default=1.0)
    type_source: str = Field(default=KnowledgeUnitTypeSource.LLM.value, index=True)
    build_revision_no: int = Field(default=0, index=True)
    current_revision_id: int | None = Field(default=None)
    merged_into_node_id: int | None = Field(default=None, foreign_key="knowledge_unit.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class KnowledgeAlias(SQLModel):
    """Structured alias payload embedded on a knowledge unit."""

    id: int | None = None
    node_id: int
    alias: str
    normalized_alias: str
    language: str = Field(default="zh")
    source: str = Field(default="llm")
    confidence: float = Field(default=1.0)
    is_primary: bool = Field(default=False)
    status: str = Field(default=KnowledgeUnitStatus.ACTIVE.value)
    created_at: datetime = Field(default_factory=utcnow)


class KnowledgeRevision(SQLModel):
    """Materialized revision view derived from the current knowledge-unit body."""

    id: int | None = None
    node_id: int
    revision_no: int
    title: str
    summary: str = ""
    body: str = ""
    revision_reason: str
    is_current: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
