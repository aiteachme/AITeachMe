"""Add user file deduplication lookup index."""

from __future__ import annotations

from alembic import op


revision = "20260428_0014"
down_revision = "20260428_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_raw_file_user_hash_size_type",
        "raw_file",
        ["user_id", "content_hash", "file_size_bytes", "filetype"],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_file_user_hash_size_type", table_name="raw_file")
