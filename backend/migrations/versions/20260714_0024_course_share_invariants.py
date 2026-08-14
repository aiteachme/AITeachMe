"""Add course-share uniqueness and import receipts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260714_0024"
down_revision = "20260624_0023"
branch_labels = None
depends_on = None

_ACTIVE_SHARE_INDEX = "uq_course_share_active_source_course"


def upgrade() -> None:
    # Existing deployments may contain several active links for one course.
    # Keep the newest stable row before adding the partial unique index.
    op.execute(
        sa.text(
            """
            WITH ranked_active_shares AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_course_id
                        ORDER BY created_at DESC, id DESC
                    ) AS row_number
                FROM course_share
                WHERE status = 'active'
            )
            UPDATE course_share
            SET
                status = 'revoked',
                revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT id
                FROM ranked_active_shares
                WHERE row_number > 1
            )
            """
        )
    )
    op.create_index(
        _ACTIVE_SHARE_INDEX,
        "course_share",
        ["source_course_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "course_share_import",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("share_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("imported_course_id", sa.String(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["share_id"], ["course_share.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "share_id",
            "user_id",
            name="uq_course_share_import_share_user",
        ),
    )
    op.create_index(
        op.f("ix_course_share_import_imported_course_id"),
        "course_share_import",
        ["imported_course_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_course_share_import_user_id"),
        "course_share_import",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_course_share_import_user_id"),
        table_name="course_share_import",
    )
    op.drop_index(
        op.f("ix_course_share_import_imported_course_id"),
        table_name="course_share_import",
    )
    op.drop_table("course_share_import")
    op.drop_index(_ACTIVE_SHARE_INDEX, table_name="course_share")
