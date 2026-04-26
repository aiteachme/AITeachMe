"""Use text columns for subject JSON string fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_0006"
down_revision = "20260425_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "subject",
        "profile_json",
        existing_type=sa.String(),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "subject",
        "settings_json",
        existing_type=sa.String(),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "subject",
        "settings_json",
        existing_type=sa.Text(),
        type_=sa.String(),
        existing_nullable=False,
    )
    op.alter_column(
        "subject",
        "profile_json",
        existing_type=sa.Text(),
        type_=sa.String(),
        existing_nullable=False,
    )
