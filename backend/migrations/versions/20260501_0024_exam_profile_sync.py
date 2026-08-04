"""Add durable exam Profile synchronization jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260501_0024"
down_revision = "20260430_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exam_profile_sync",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_paper_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("trigger", sa.String(), nullable=False, server_default="exam_graded"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claim_token", sa.String(), nullable=False, server_default=""),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(), nullable=False, server_default=""),
        sa.Column("states_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_task_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["course.id"]),
        sa.ForeignKeyConstraint(["exam_paper_id"], ["exam_paper.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_paper_id", name="uq_exam_profile_sync_paper"),
    )
    op.create_index(op.f("ix_exam_profile_sync_completed_at"), "exam_profile_sync", ["completed_at"], unique=False)
    op.create_index(op.f("ix_exam_profile_sync_course_id"), "exam_profile_sync", ["course_id"], unique=False)
    op.create_index(op.f("ix_exam_profile_sync_exam_paper_id"), "exam_profile_sync", ["exam_paper_id"], unique=False)
    op.create_index(op.f("ix_exam_profile_sync_lease_expires_at"), "exam_profile_sync", ["lease_expires_at"], unique=False)
    op.create_index(op.f("ix_exam_profile_sync_next_attempt_at"), "exam_profile_sync", ["next_attempt_at"], unique=False)
    op.create_index("ix_exam_profile_sync_recovery", "exam_profile_sync", ["status", "next_attempt_at"], unique=False)
    op.create_index(op.f("ix_exam_profile_sync_status"), "exam_profile_sync", ["status"], unique=False)
    op.create_index(op.f("ix_exam_profile_sync_user_id"), "exam_profile_sync", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_exam_profile_sync_user_id"), table_name="exam_profile_sync")
    op.drop_index(op.f("ix_exam_profile_sync_status"), table_name="exam_profile_sync")
    op.drop_index("ix_exam_profile_sync_recovery", table_name="exam_profile_sync")
    op.drop_index(op.f("ix_exam_profile_sync_next_attempt_at"), table_name="exam_profile_sync")
    op.drop_index(op.f("ix_exam_profile_sync_lease_expires_at"), table_name="exam_profile_sync")
    op.drop_index(op.f("ix_exam_profile_sync_exam_paper_id"), table_name="exam_profile_sync")
    op.drop_index(op.f("ix_exam_profile_sync_course_id"), table_name="exam_profile_sync")
    op.drop_index(op.f("ix_exam_profile_sync_completed_at"), table_name="exam_profile_sync")
    op.drop_table("exam_profile_sync")
