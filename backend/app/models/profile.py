"""Active profile-domain data models."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class UserKnowledgeState(SQLModel, table=True):
    """Knowledge mastery state bound to one teaching unit or one knowledge node."""

    __tablename__ = "user_knowledge_state"
    __table_args__ = (
        sa.CheckConstraint(
            (
                "(teaching_unit_id IS NOT NULL AND knowledge_node_id IS NULL) "
                "OR (teaching_unit_id IS NULL AND knowledge_node_id IS NOT NULL)"
            ),
            name="ck_user_knowledge_state_target",
        ),
        sa.Index(
            "uq_user_knowledge_state_unit",
            "user_id",
            "subject",
            "teaching_unit_id",
            unique=True,
            sqlite_where=sa.text("knowledge_node_id IS NULL"),
            postgresql_where=sa.text("knowledge_node_id IS NULL"),
        ),
        sa.Index(
            "uq_user_knowledge_state_node",
            "user_id",
            "subject",
            "knowledge_node_id",
            unique=True,
            sqlite_where=sa.text("teaching_unit_id IS NULL"),
            postgresql_where=sa.text("teaching_unit_id IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    teaching_unit_id: int | None = Field(default=None, foreign_key="teaching_unit.id", index=True)
    knowledge_node_id: int | None = Field(default=None, foreign_key="knowledge_node.id", index=True)
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
    stats_json: str = Field(default="{}")
    updated_at: datetime = Field(default_factory=utcnow)


class ReviewTask(SQLModel, table=True):
    """Scheduled review task."""

    __tablename__ = "review_task"
    __table_args__ = (
        sa.CheckConstraint(
            (
                "(teaching_unit_id IS NOT NULL AND knowledge_node_id IS NULL) "
                "OR (teaching_unit_id IS NULL AND knowledge_node_id IS NOT NULL)"
            ),
            name="ck_review_task_target",
        ),
        sa.Index(
            "uq_review_task_pending_unit",
            "user_id",
            "subject",
            "teaching_unit_id",
            unique=True,
            sqlite_where=sa.text("knowledge_node_id IS NULL AND status = 'pending'"),
            postgresql_where=sa.text("knowledge_node_id IS NULL AND status = 'pending'"),
        ),
        sa.Index(
            "uq_review_task_pending_node",
            "user_id",
            "subject",
            "knowledge_node_id",
            unique=True,
            sqlite_where=sa.text("teaching_unit_id IS NULL AND status = 'pending'"),
            postgresql_where=sa.text("teaching_unit_id IS NULL AND status = 'pending'"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    task_type: str
    teaching_unit_id: int | None = Field(default=None, foreign_key="teaching_unit.id", index=True)
    knowledge_node_id: int | None = Field(default=None, foreign_key="knowledge_node.id", index=True)
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
