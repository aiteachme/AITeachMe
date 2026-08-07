"""Persist the selected model tier for the durable initial-exam job."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260504_0027"
down_revision = "20260503_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_initial_exam_job",
        sa.Column("model_override", sa.String(), nullable=False, server_default=""),
    )
    op.create_check_constraint(
        "ck_course_initial_exam_job_model_override",
        "course_initial_exam_job",
        "model_override IN ('', 'light', 'primary', 'reason')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_course_initial_exam_job_model_override",
        "course_initial_exam_job",
        type_="check",
    )
    op.drop_column("course_initial_exam_job", "model_override")
