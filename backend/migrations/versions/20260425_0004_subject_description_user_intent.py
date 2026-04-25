"""Add subject description and user intent.

Subject description and user intent are mutable free-text fields updated by
runtime workflows and UI actions.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_0004"
down_revision = "20260425_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subject",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "subject",
        sa.Column("user_intent", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("subject", "description", server_default=None)
    op.alter_column("subject", "user_intent", server_default=None)


def downgrade() -> None:
    op.drop_column("subject", "user_intent")
    op.drop_column("subject", "description")
