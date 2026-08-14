"""Persist mastery-drill sessions and every answer attempt."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260502_0025"
down_revision = "20260501_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mastery_drill_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_paper_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, server_default="local"),
        sa.Column("session_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("config_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("total_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_key", sa.String(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("total_attempts >= 0", name="ck_mastery_drill_session_total_attempts"),
        sa.CheckConstraint("wrong_attempts >= 0", name="ck_mastery_drill_session_wrong_attempts"),
        sa.ForeignKeyConstraint(["course_id"], ["course.id"]),
        sa.ForeignKeyConstraint(["exam_paper_id"], ["exam_paper.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_paper_id", name="uq_mastery_drill_session_paper"),
        sa.UniqueConstraint(
            "course_id",
            "user_id",
            "session_key",
            name="uq_mastery_drill_session_key",
        ),
    )
    op.create_index(
        "ix_mastery_drill_session_active",
        "mastery_drill_session",
        ["course_id", "user_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "uq_mastery_drill_session_course_user_active",
        "mastery_drill_session",
        ["course_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_index(op.f("ix_mastery_drill_session_completed_at"), "mastery_drill_session", ["completed_at"], unique=False)
    op.create_index(op.f("ix_mastery_drill_session_course_id"), "mastery_drill_session", ["course_id"], unique=False)
    op.create_index(op.f("ix_mastery_drill_session_exam_paper_id"), "mastery_drill_session", ["exam_paper_id"], unique=False)
    op.create_index(op.f("ix_mastery_drill_session_status"), "mastery_drill_session", ["status"], unique=False)
    op.create_index(op.f("ix_mastery_drill_session_user_id"), "mastery_drill_session", ["user_id"], unique=False)

    op.create_table(
        "mastery_drill_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mastery_drill_session_id", sa.Integer(), nullable=False),
        sa.Column("exam_paper_item_id", sa.Integer(), nullable=False),
        sa.Column("question_template_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attempt_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="grading"),
        sa.Column("answer_content", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score_obtained", sa.Float(), nullable=True),
        sa.Column("score_max", sa.Float(), nullable=True),
        sa.Column("feedback_text", sa.Text(), nullable=True),
        sa.Column("error_cause_label", sa.String(), nullable=True),
        sa.Column("grading_mode", sa.String(), nullable=False, server_default=""),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=True),
        sa.Column("hint_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence_self_report", sa.Integer(), nullable=True),
        sa.Column("claim_token", sa.String(), nullable=False, server_default=""),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=False, server_default=""),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("attempt_no >= 1", name="ck_mastery_drill_attempt_no"),
        sa.CheckConstraint(
            "confidence_self_report IS NULL OR (confidence_self_report >= 1 AND confidence_self_report <= 5)",
            name="ck_mastery_drill_attempt_confidence",
        ),
        sa.CheckConstraint(
            "time_spent_seconds IS NULL OR time_spent_seconds >= 0",
            name="ck_mastery_drill_attempt_time",
        ),
        sa.ForeignKeyConstraint(["exam_paper_item_id"], ["exam_paper_item.id"]),
        sa.ForeignKeyConstraint(["mastery_drill_session_id"], ["mastery_drill_session.id"]),
        sa.ForeignKeyConstraint(["question_template_id"], ["question_template.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mastery_drill_session_id",
            "attempt_key",
            name="uq_mastery_drill_attempt_key",
        ),
    )
    op.create_index(op.f("ix_mastery_drill_attempt_answered_at"), "mastery_drill_attempt", ["answered_at"], unique=False)
    op.create_index(op.f("ix_mastery_drill_attempt_exam_paper_item_id"), "mastery_drill_attempt", ["exam_paper_item_id"], unique=False)
    op.create_index("ix_mastery_drill_attempt_item_created", "mastery_drill_attempt", ["exam_paper_item_id", "created_at"], unique=False)
    op.create_index(op.f("ix_mastery_drill_attempt_lease_expires_at"), "mastery_drill_attempt", ["lease_expires_at"], unique=False)
    op.create_index(op.f("ix_mastery_drill_attempt_mastery_drill_session_id"), "mastery_drill_attempt", ["mastery_drill_session_id"], unique=False)
    op.create_index(op.f("ix_mastery_drill_attempt_question_template_id"), "mastery_drill_attempt", ["question_template_id"], unique=False)
    op.create_index("ix_mastery_drill_attempt_session_status", "mastery_drill_attempt", ["mastery_drill_session_id", "status"], unique=False)
    op.create_index(op.f("ix_mastery_drill_attempt_status"), "mastery_drill_attempt", ["status"], unique=False)
    op.create_index(
        "uq_mastery_drill_attempt_item_grading",
        "mastery_drill_attempt",
        ["exam_paper_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'grading'"),
        sqlite_where=sa.text("status = 'grading'"),
    )


def downgrade() -> None:
    op.drop_index("uq_mastery_drill_attempt_item_grading", table_name="mastery_drill_attempt")
    op.drop_index(op.f("ix_mastery_drill_attempt_status"), table_name="mastery_drill_attempt")
    op.drop_index("ix_mastery_drill_attempt_session_status", table_name="mastery_drill_attempt")
    op.drop_index(op.f("ix_mastery_drill_attempt_question_template_id"), table_name="mastery_drill_attempt")
    op.drop_index(op.f("ix_mastery_drill_attempt_mastery_drill_session_id"), table_name="mastery_drill_attempt")
    op.drop_index(op.f("ix_mastery_drill_attempt_lease_expires_at"), table_name="mastery_drill_attempt")
    op.drop_index("ix_mastery_drill_attempt_item_created", table_name="mastery_drill_attempt")
    op.drop_index(op.f("ix_mastery_drill_attempt_exam_paper_item_id"), table_name="mastery_drill_attempt")
    op.drop_index(op.f("ix_mastery_drill_attempt_answered_at"), table_name="mastery_drill_attempt")
    op.drop_table("mastery_drill_attempt")

    op.drop_index(op.f("ix_mastery_drill_session_user_id"), table_name="mastery_drill_session")
    op.drop_index(op.f("ix_mastery_drill_session_status"), table_name="mastery_drill_session")
    op.drop_index(op.f("ix_mastery_drill_session_exam_paper_id"), table_name="mastery_drill_session")
    op.drop_index(op.f("ix_mastery_drill_session_course_id"), table_name="mastery_drill_session")
    op.drop_index(op.f("ix_mastery_drill_session_completed_at"), table_name="mastery_drill_session")
    op.drop_index("uq_mastery_drill_session_course_user_active", table_name="mastery_drill_session")
    op.drop_index("ix_mastery_drill_session_active", table_name="mastery_drill_session")
    op.drop_table("mastery_drill_session")
