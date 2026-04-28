"""Drop redundant question knowledge-unit role column."""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "20260427_0012"
down_revision = "20260427_0011"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    if context.is_offline_mode():
        op.execute(
            "ALTER TABLE question_knowledge_unit_link "
            "DROP COLUMN IF EXISTS role "
            "/* atm-allow-destructive-ddl: redundant role copied into coverage-only links */"
        )
        return
    if _has_column("question_knowledge_unit_link", "role"):
        op.drop_column("question_knowledge_unit_link", "role")


def downgrade() -> None:
    if context.is_offline_mode():
        op.execute(
            "ALTER TABLE question_knowledge_unit_link "
            "ADD COLUMN IF NOT EXISTS role VARCHAR DEFAULT 'secondary' NOT NULL"
        )
        return
    if not _has_column("question_knowledge_unit_link", "role"):
        op.add_column(
            "question_knowledge_unit_link",
            sa.Column("role", sa.String(), nullable=False, server_default="secondary"),
        )
