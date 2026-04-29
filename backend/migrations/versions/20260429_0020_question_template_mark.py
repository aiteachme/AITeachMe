"""Add question template mark flag."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260429_0020"
down_revision = "20260429_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "question_template",
        sa.Column("is_marked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_question_template_is_marked", "question_template", ["is_marked"])


def downgrade() -> None:
    op.drop_index("ix_question_template_is_marked", table_name="question_template")
    op.drop_column("question_template", "is_marked")
