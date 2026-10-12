"""Purge retired custom questions and drop their package/runtime schema.

This migration intentionally deletes historical custom-type records. Back up
the database before upgrading; retained built-in records are not deleted.
"""

from alembic import op

from app.shared.infra.database.question_type_cleanup import (
    cleanup_statements,
    finish_cleanup_statements,
    postgres_schema_statements,
)

revision = '20261012_0033'
down_revision = '20260912_0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in [*cleanup_statements('postgresql'), *postgres_schema_statements(), *finish_cleanup_statements()]:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError('Deleted custom-question history cannot be restored by downgrade; restore a database backup.')
