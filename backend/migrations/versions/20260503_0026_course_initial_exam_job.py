"""Persist the one automatic initial exam job per course."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260503_0026"
down_revision = "20260502_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_initial_exam_job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, server_default="local"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("build_session_id", sa.String(), nullable=False, server_default=""),
        sa.Column("exam_paper_id", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("claim_token", sa.String(), nullable=False, server_default=""),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_course_initial_exam_job_attempt_count"),
        sa.ForeignKeyConstraint(["course_id"], ["course.id"]),
        sa.ForeignKeyConstraint(["exam_paper_id"], ["exam_paper.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", name="uq_course_initial_exam_job_course"),
    )
    op.create_index(op.f("ix_course_initial_exam_job_completed_at"), "course_initial_exam_job", ["completed_at"], unique=False)
    op.create_index(op.f("ix_course_initial_exam_job_course_id"), "course_initial_exam_job", ["course_id"], unique=False)
    op.create_index(op.f("ix_course_initial_exam_job_exam_paper_id"), "course_initial_exam_job", ["exam_paper_id"], unique=False)
    op.create_index(op.f("ix_course_initial_exam_job_lease_expires_at"), "course_initial_exam_job", ["lease_expires_at"], unique=False)
    op.create_index(op.f("ix_course_initial_exam_job_next_attempt_at"), "course_initial_exam_job", ["next_attempt_at"], unique=False)
    op.create_index("ix_course_initial_exam_job_recovery", "course_initial_exam_job", ["status", "next_attempt_at"], unique=False)
    op.create_index(op.f("ix_course_initial_exam_job_status"), "course_initial_exam_job", ["status"], unique=False)
    op.create_index(op.f("ix_course_initial_exam_job_user_id"), "course_initial_exam_job", ["user_id"], unique=False)

    # Existing/imported courses must not suddenly receive an automatic exam on
    # deployment. New course builds create their pending marker explicitly.
    op.execute(
        sa.text(
            """
            INSERT INTO course_initial_exam_job (
                course_id, user_id, status, build_session_id, exam_paper_id,
                attempt_count, next_attempt_at, claim_token, lease_expires_at,
                last_error_code, started_at, completed_at, created_at, updated_at
            )
            SELECT
                course.id,
                course.user_id,
                'completed',
                '',
                (
                    SELECT exam_paper.id
                    FROM exam_paper
                    WHERE exam_paper.course_id = course.id
                      AND exam_paper.generation_origin = 'prewarm'
                    ORDER BY exam_paper.created_at ASC, exam_paper.id ASC
                    LIMIT 1
                ),
                0,
                NULL,
                '',
                NULL,
                'legacy_course_backfill',
                NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM course
            """
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_course_initial_exam_job_user_id"), table_name="course_initial_exam_job")
    op.drop_index(op.f("ix_course_initial_exam_job_status"), table_name="course_initial_exam_job")
    op.drop_index("ix_course_initial_exam_job_recovery", table_name="course_initial_exam_job")
    op.drop_index(op.f("ix_course_initial_exam_job_next_attempt_at"), table_name="course_initial_exam_job")
    op.drop_index(op.f("ix_course_initial_exam_job_lease_expires_at"), table_name="course_initial_exam_job")
    op.drop_index(op.f("ix_course_initial_exam_job_exam_paper_id"), table_name="course_initial_exam_job")
    op.drop_index(op.f("ix_course_initial_exam_job_course_id"), table_name="course_initial_exam_job")
    op.drop_index(op.f("ix_course_initial_exam_job_completed_at"), table_name="course_initial_exam_job")
    op.drop_table("course_initial_exam_job")
