"""Add course description and user intent.

Course description and user intent are mutable free-text fields updated by
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
        "course",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "course",
        sa.Column("user_intent", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("course", "description", server_default=None)
    op.alter_column("course", "user_intent", server_default=None)


def downgrade() -> None:
    op.drop_column("course", "user_intent")
    op.drop_column("course", "description")
