"""Keep raw-file origin course as audit data only."""

from __future__ import annotations

from alembic import op


revision = "20260429_0019"
down_revision = "20260428_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    op.execute(
        """
        DO $$
        DECLARE
            constraint_name text;
        BEGIN
            FOR constraint_name IN
                SELECT c.conname
                FROM pg_constraint AS c
                JOIN pg_class AS t ON t.oid = c.conrelid
                JOIN pg_namespace AS n ON n.oid = t.relnamespace
                JOIN pg_attribute AS a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
                JOIN pg_class AS rt ON rt.oid = c.confrelid
                WHERE n.nspname = current_schema()
                  AND c.contype = 'f'
                  AND t.relname = 'raw_file'
                  AND a.attname = 'origin_course_id'
                  AND rt.relname = 'course'
            LOOP
                EXECUTE format('ALTER TABLE raw_file DROP CONSTRAINT IF EXISTS %I', constraint_name);
            END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Downgrading raw_file origin course audit semantics is not supported.")
