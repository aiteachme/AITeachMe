"""Active profile-domain data models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class UserKnowledgeState(SQLModel, table=True):
    """Knowledge mastery state for unit/node granularity."""

    __tablename__ = "user_knowledge_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject",
            "granularity",
            "target_id",
            name="uq_knowledge_state",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    granularity: str
    target_id: int = Field(index=True)
    mastery_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    stability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    forgetting_due_at: datetime | None = Field(default=None)
    review_priority: float = Field(default=0.0)
    total_attempts: int = Field(default=0, ge=0)
    correct_attempts: int = Field(default=0, ge=0)
    last_attempt_at: datetime | None = Field(default=None)
    state_version: int = Field(default=1, ge=1)
    last_recomputed_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow)


class ReviewTask(SQLModel, table=True):
    """Scheduled review task."""

    __tablename__ = "review_task"
    __table_args__ = (
        Index(
            "ix_review_task_target_status",
            "user_id",
            "subject",
            "target_id",
            "target_granularity",
            "status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    task_type: str
    target_id: int = Field(index=True)
    target_granularity: str
    priority: float = Field(default=0.0)
    scheduled_at: datetime
    status: str = Field(default="pending", index=True)
    interval_days: int = Field(default=1, ge=1)
    ease_factor: float = Field(default=2.5, ge=1.3)
    repetition_count: int = Field(default=0, ge=0)
    reason: str | None = Field(default=None)
    source_state_id: int | None = Field(default=None, foreign_key="user_knowledge_state.id", index=True)
    source_exam_paper_id: int | None = Field(default=None, foreign_key="exam_paper.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = Field(default=None)
    expired_at: datetime | None = Field(default=None)
