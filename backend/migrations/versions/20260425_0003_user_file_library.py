"""Split raw files from subject ownership.

Files now belong to a user-level library and can be linked to zero or more
subjects through subject_file.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_0003"
down_revision = "20260423_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "raw_file",
        sa.Column("user_id", sa.String(), nullable=False, server_default="local"),
    )
    op.create_index("ix_raw_file_user_id", "raw_file", ["user_id"])
    op.alter_column("raw_file", "subject", existing_type=sa.String(), nullable=True)

    op.create_table(
        "subject_file",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("raw_file_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["subject"], ["subject.slug"]),
        sa.ForeignKeyConstraint(["raw_file_id"], ["raw_file.id"]),
        sa.UniqueConstraint("user_id", "subject", "raw_file_id", name="uq_subject_file_user_subject_raw_file"),
    )
    op.create_index("ix_subject_file_user_id", "subject_file", ["user_id"])
    op.create_index("ix_subject_file_subject", "subject_file", ["subject"])
    op.create_index("ix_subject_file_raw_file_id", "subject_file", ["raw_file_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO subject_file (user_id, subject, raw_file_id, created_at, updated_at)
            SELECT COALESCE(user_id, 'local'), subject, id, created_at, updated_at
            FROM raw_file
            WHERE subject IS NOT NULL AND subject <> ''
            ON CONFLICT ON CONSTRAINT uq_subject_file_user_subject_raw_file DO NOTHING
            """
        )
    )
    op.alter_column("raw_file", "user_id", server_default=None)


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE raw_file
            SET subject = COALESCE(NULLIF(subject, ''), 'legacy_unassigned')
            WHERE subject IS NULL OR subject = ''
            """
        )
    )
    op.drop_index("ix_subject_file_raw_file_id", table_name="subject_file")
    op.drop_index("ix_subject_file_subject", table_name="subject_file")
    op.drop_index("ix_subject_file_user_id", table_name="subject_file")
    op.drop_table("subject_file")
    op.alter_column("raw_file", "subject", existing_type=sa.String(), nullable=False)
    op.drop_index("ix_raw_file_user_id", table_name="raw_file")
    op.drop_column("raw_file", "user_id")
