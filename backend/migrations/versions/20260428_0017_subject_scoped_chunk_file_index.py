"""Scope retrieval chunk file indexes by subject."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0017"
down_revision = "20260428_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    op.execute(sa.text("ALTER TABLE retrieval_chunk DROP CONSTRAINT IF EXISTS uq_retrieval_chunk_file_id_chunk_index"))
    op.execute(sa.text("ALTER TABLE retrieval_chunk DROP CONSTRAINT IF EXISTS uq_retrieval_chunk_document_id_chunk_index"))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'uq_retrieval_chunk_subject_file_id_chunk_index'
                      AND conrelid = 'public.retrieval_chunk'::regclass
                ) THEN
                    ALTER TABLE retrieval_chunk
                    ADD CONSTRAINT uq_retrieval_chunk_subject_file_id_chunk_index
                    UNIQUE (subject, file_id, chunk_index);
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    op.execute(
        sa.text(
            "ALTER TABLE retrieval_chunk "
            "DROP CONSTRAINT IF EXISTS uq_retrieval_chunk_subject_file_id_chunk_index"
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'uq_retrieval_chunk_file_id_chunk_index'
                      AND conrelid = 'public.retrieval_chunk'::regclass
                ) THEN
                    ALTER TABLE retrieval_chunk
                    ADD CONSTRAINT uq_retrieval_chunk_file_id_chunk_index
                    UNIQUE (file_id, chunk_index);
                END IF;
            END $$;
            """
        )
    )
