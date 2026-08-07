"""Durable state for the one automatic exam created for a new course."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class CourseInitialExamJob(SQLModel, table=True):
    """One durable, retryable initial-exam job per course."""

    __tablename__ = "course_initial_exam_job"
    __table_args__ = (
        UniqueConstraint("course_id", name="uq_course_initial_exam_job_course"),
        sa.CheckConstraint(
            "model_override IN ('', 'light', 'primary', 'reason')",
            name="ck_course_initial_exam_job_model_override",
        ),
        sa.Index("ix_course_initial_exam_job_recovery", "status", "next_attempt_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    course_id: str = Field(foreign_key="course.id", index=True)
    user_id: str = Field(default="local", index=True)
    status: str = Field(default="pending", index=True)
    build_session_id: str = Field(default="")
    model_override: str = Field(
        default="",
        sa_column=sa.Column(sa.String(), nullable=False, server_default=""),
    )
    exam_paper_id: int | None = Field(
        default=None,
        sa_column=sa.Column(
            sa.Integer,
            sa.ForeignKey("exam_paper.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    attempt_count: int = Field(default=0, ge=0)
    next_attempt_at: datetime | None = Field(default_factory=utcnow, index=True)
    claim_token: str = Field(default="")
    lease_expires_at: datetime | None = Field(default=None, index=True)
    last_error_code: str = Field(default="")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
