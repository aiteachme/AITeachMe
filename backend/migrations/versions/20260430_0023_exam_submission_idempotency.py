"""Add idempotent exam submission and grading leases."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260430_0023"
down_revision = "20260429_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exam_paper",
        sa.Column("submission_key", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "exam_paper",
        sa.Column("submission_hash", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "exam_paper",
        sa.Column("grading_claim_token", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "exam_paper",
        sa.Column("grading_lease_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "exam_paper",
        sa.Column("grading_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "exam_paper",
        sa.Column("grading_last_error", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        op.f("ix_exam_paper_grading_lease_expires_at"),
        "exam_paper",
        ["grading_lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_exam_paper_grading_recovery",
        "exam_paper",
        ["status", "grading_lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_exam_paper_grading_recovery", table_name="exam_paper")
    op.drop_index(op.f("ix_exam_paper_grading_lease_expires_at"), table_name="exam_paper")
    op.drop_column("exam_paper", "grading_last_error")
    op.drop_column("exam_paper", "grading_attempts")
    op.drop_column("exam_paper", "grading_lease_expires_at")
    op.drop_column("exam_paper", "grading_claim_token")
    op.drop_column("exam_paper", "submission_hash")
    op.drop_column("exam_paper", "submission_key")
