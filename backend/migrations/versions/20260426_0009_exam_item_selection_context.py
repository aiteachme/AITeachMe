"""Add exam item selection context."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0009"
down_revision = "20260426_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exam_paper_item",
        sa.Column("selection_context_json", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("exam_paper_item", "selection_context_json")
