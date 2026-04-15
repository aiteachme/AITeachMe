"""Active profile-domain data models."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class UserKnowledgeState(SQLModel, table=True):
    """Knowledge mastery state bound to one knowledge node."""

    __tablename__ = "user_knowledge_state"
    __table_args__ = (
        sa.Index(
            "uq_user_knowledge_state_node",
            "user_id",
            "subject",
            "knowledge_node_id",
            unique=True,
            sqlite_where=sa.text("knowledge_node_id IS NOT NULL"),
            postgresql_where=sa.text("knowledge_node_id IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    knowledge_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    mastery_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    stability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    forgetting_due_at: datetime | None = Field(default=None)
    review_priority: float = Field(default=0.0)
    total_attempts: int = Field(default=0, ge=0)
    correct_attempts: int = Field(default=0, ge=0)
    last_attempt_at: datetime | None = Field(default=None)
    review_status: str = Field(default="idle", index=True)
    scheduled_review_at: datetime | None = Field(default=None, index=True)
    review_interval_days: int = Field(default=1, ge=1)
    review_ease_factor: float = Field(default=2.5, ge=1.3)
    review_repetition_count: int = Field(default=0, ge=0)
    review_reason: str | None = Field(default=None)
    source_exam_paper_id: int | None = Field(default=None, foreign_key="exam_paper.id", index=True)
    state_version: int = Field(default=1, ge=1)
    last_recomputed_at: datetime | None = Field(default=None)
    stats_json: str = Field(default="{}")
    updated_at: datetime = Field(default_factory=utcnow)
