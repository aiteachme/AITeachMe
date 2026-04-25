"""Add exam paper preview payload."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0006"
down_revision = "20260425_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exam_paper",
        sa.Column("paper_preview_json", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("exam_paper", "paper_preview_json")
