"""Add course share snapshots."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260624_0023"
down_revision = "20260429_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "course_share",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("source_course_id", sa.String(), nullable=False),
        sa.Column("token", sa.String(length=160), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("course_name", sa.String(), nullable=False),
        sa.Column("course_description", sa.Text(), nullable=False),
        sa.Column("course_icon_key", sa.String(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("stats_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("import_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_imported_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"]),
    )
    op.create_index(op.f("ix_course_share_created_at"), "course_share", ["created_at"], unique=False)
    op.create_index(op.f("ix_course_share_expires_at"), "course_share", ["expires_at"], unique=False)
    op.create_index(op.f("ix_course_share_owner_user_id"), "course_share", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_course_share_revoked_at"), "course_share", ["revoked_at"], unique=False)
    op.create_index(op.f("ix_course_share_source_course_id"), "course_share", ["source_course_id"], unique=False)
    op.create_index(op.f("ix_course_share_status"), "course_share", ["status"], unique=False)
    op.create_index(op.f("ix_course_share_token"), "course_share", ["token"], unique=True)
    op.create_index(op.f("ix_course_share_token_hash"), "course_share", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_course_share_token_hash"), table_name="course_share")
    op.drop_index(op.f("ix_course_share_token"), table_name="course_share")
    op.drop_index(op.f("ix_course_share_status"), table_name="course_share")
    op.drop_index(op.f("ix_course_share_source_course_id"), table_name="course_share")
    op.drop_index(op.f("ix_course_share_revoked_at"), table_name="course_share")
    op.drop_index(op.f("ix_course_share_owner_user_id"), table_name="course_share")
    op.drop_index(op.f("ix_course_share_expires_at"), table_name="course_share")
    op.drop_index(op.f("ix_course_share_created_at"), table_name="course_share")
    op.drop_table("course_share")
