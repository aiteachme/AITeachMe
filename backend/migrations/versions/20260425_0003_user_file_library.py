"""Split raw files from course ownership.

Files now belong to a user-level library and can be linked to zero or more
courses through course_file.
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
    op.alter_column("raw_file", "course", existing_type=sa.String(), nullable=True)

    op.execute(
        sa.text(
            """
            UPDATE raw_file AS rf
            SET user_id = s.user_id
            FROM course AS s
            WHERE rf.course = s.slug
              AND rf.course IS NOT NULL
              AND rf.course <> ''
              AND (rf.user_id IS NULL OR rf.user_id = '' OR rf.user_id = 'local')
            """
        )
    )

    op.create_table(
        "course_file",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("course", sa.String(), nullable=False),
        sa.Column("raw_file_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["course"], ["course.slug"]),
        sa.ForeignKeyConstraint(["raw_file_id"], ["raw_file.id"]),
        sa.UniqueConstraint("user_id", "course", "raw_file_id", name="uq_course_file_user_course_raw_file"),
    )
    op.create_index("ix_course_file_user_id", "course_file", ["user_id"])
    op.create_index("ix_course_file_course", "course_file", ["course"])
    op.create_index("ix_course_file_raw_file_id", "course_file", ["raw_file_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO course_file (user_id, course, raw_file_id, created_at, updated_at)
            SELECT rf.user_id, rf.course, rf.id, rf.created_at, rf.updated_at
            FROM raw_file AS rf
            JOIN course AS s
              ON s.slug = rf.course
             AND s.user_id = rf.user_id
            WHERE rf.course IS NOT NULL AND rf.course <> ''
              AND rf.user_id IS NOT NULL AND rf.user_id <> ''
            ON CONFLICT ON CONSTRAINT uq_course_file_user_course_raw_file DO NOTHING
            """
        )
    )
    op.alter_column("raw_file", "user_id", server_default=None)


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE raw_file
            SET course = COALESCE(NULLIF(course, ''), 'legacy_unassigned')
            WHERE course IS NULL OR course = ''
            """
        )
    )
    op.drop_index("ix_course_file_raw_file_id", table_name="course_file")
    op.drop_index("ix_course_file_course", table_name="course_file")
    op.drop_index("ix_course_file_user_id", table_name="course_file")
    op.drop_table("course_file")
    op.alter_column("raw_file", "course", existing_type=sa.String(), nullable=False)
    op.drop_index("ix_raw_file_user_id", table_name="raw_file")
    op.drop_column("raw_file", "user_id")
