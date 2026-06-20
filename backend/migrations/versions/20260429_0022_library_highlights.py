"""Add library file highlights."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260429_0022"
down_revision = "20260429_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_session", sa.Column("library_file_id", sa.String(), nullable=True))
    op.create_index(
        op.f("ix_chat_session_library_file_id"),
        "chat_session",
        ["library_file_id"],
        unique=False,
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE chat_session
            SET library_file_id = substring(source from 19)
            WHERE (library_file_id IS NULL OR library_file_id = '')
            AND source LIKE 'library_selection:%'
            AND length(source) >= 19
            """
        )
    else:
        op.execute(
            """
            UPDATE chat_session
            SET library_file_id = substr(source, 19)
            WHERE (library_file_id IS NULL OR library_file_id = '')
            AND source LIKE 'library_selection:%'
            AND length(source) >= 19
            """
        )
    op.execute(
        """
        UPDATE chat_session
        SET course_id = ''
        WHERE course_id = 'global'
        AND source LIKE 'library_selection:%'
        """
    )
    op.execute(
        """
        UPDATE chat_message
        SET course_id = ''
        WHERE course_id = 'global'
        AND source LIKE 'library_selection:%'
        """
    )
    op.create_table(
        "highlight",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("file_id", sa.String(), nullable=False),
        sa.Column("selected_text", sa.Text(), nullable=False),
        sa.Column("anchor_id", sa.Text(), nullable=True),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("interactive_html", sa.Text(), nullable=True),
        sa.Column("segments_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_highlight_created_at"), "highlight", ["created_at"], unique=False)
    op.create_index(op.f("ix_highlight_file_id"), "highlight", ["file_id"], unique=False)
    op.create_index(op.f("ix_highlight_user_id"), "highlight", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_highlight_user_id"), table_name="highlight")
    op.drop_index(op.f("ix_highlight_file_id"), table_name="highlight")
    op.drop_index(op.f("ix_highlight_created_at"), table_name="highlight")
    op.drop_table("highlight")
    op.drop_index(op.f("ix_chat_session_library_file_id"), table_name="chat_session")
    op.drop_column("chat_session", "library_file_id")
