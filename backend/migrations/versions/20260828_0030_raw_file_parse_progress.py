"""Persist live raw-file parsing progress."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260828_0030"
down_revision = "20260815_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_file",
        sa.Column("parse_progress_json", sa.Text(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("raw_file", "parse_progress_json")
