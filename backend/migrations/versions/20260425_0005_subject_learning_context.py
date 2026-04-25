"""Add subject learning context snapshot fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260425_0005"
down_revision = "20260425_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subject",
        sa.Column("learning_intent_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "subject",
        sa.Column("subject_intro_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "subject",
        sa.Column("document_summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "subject",
        sa.Column("llm_context_text", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("subject", "llm_context_text")
    op.drop_column("subject", "document_summary_json")
    op.drop_column("subject", "subject_intro_text")
    op.drop_column("subject", "learning_intent_text")
