"""Use raw file public IDs as primary keys."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0016"
down_revision = "20260428_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    op.execute(
        sa.text(
            """
            CREATE TEMP TABLE atm_raw_file_id_map AS
            SELECT id::text AS old_id,
                   uid AS file_id
            FROM raw_file
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION pg_temp.atm_remap_file_id_array(value jsonb)
            RETURNS jsonb
            LANGUAGE sql
            AS $$
                SELECT COALESCE(
                    jsonb_agg(COALESCE(mapping.file_id, item.value) ORDER BY item.ordinality),
                    '[]'::jsonb
                )
                FROM jsonb_array_elements_text(COALESCE(value, '[]'::jsonb))
                    WITH ORDINALITY AS item(value, ordinality)
                LEFT JOIN atm_raw_file_id_map AS mapping
                  ON mapping.old_id = item.value
                  OR mapping.file_id = item.value
            $$
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE knowledge_document
            SET source_file_ids = pg_temp.atm_remap_file_id_array(
                COALESCE(NULLIF(source_file_ids, '')::jsonb, '[]'::jsonb)
            )::text
            WHERE source_file_ids IS NOT NULL
              AND source_file_ids <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_graph_source_ref
            SET source_file_ids_json = pg_temp.atm_remap_file_id_array(
                COALESCE(NULLIF(source_file_ids_json, '')::jsonb, '[]'::jsonb)
            )::text
            WHERE source_file_ids_json IS NOT NULL
              AND source_file_ids_json <> ''
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE chat_session
            SET meta_json = jsonb_set(
                meta_json::jsonb,
                '{selected_file_ids}',
                pg_temp.atm_remap_file_id_array(meta_json::jsonb->'selected_file_ids'),
                true
            )::json
            WHERE meta_json IS NOT NULL
              AND meta_json::jsonb ? 'selected_file_ids'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE chat_session
            SET meta_json = jsonb_set(
                meta_json::jsonb,
                '{confirmed_plan,selected_file_ids_json}',
                pg_temp.atm_remap_file_id_array(
                    meta_json::jsonb #> '{confirmed_plan,selected_file_ids_json}'
                ),
                true
            )::json
            WHERE meta_json IS NOT NULL
              AND meta_json::jsonb #> '{confirmed_plan,selected_file_ids_json}' IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE chat_session
            SET meta_json = jsonb_set(
                meta_json::jsonb,
                '{confirmed_plan,selected_file_ids}',
                pg_temp.atm_remap_file_id_array(
                    meta_json::jsonb #> '{confirmed_plan,selected_file_ids}'
                ),
                true
            )::json
            WHERE meta_json IS NOT NULL
              AND meta_json::jsonb #> '{confirmed_plan,selected_file_ids}' IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF to_regclass('public.confirmed_build_plan') IS NOT NULL THEN
                    EXECUTE $sql$
                        UPDATE confirmed_build_plan
                        SET selected_file_ids_json = pg_temp.atm_remap_file_id_array(
                            COALESCE(to_jsonb(selected_file_ids_json), '[]'::jsonb)
                        )::json
                    $sql$;
                END IF;
            END $$;
            """
        )
    )

    op.execute(sa.text("ALTER TABLE subject_file DROP CONSTRAINT IF EXISTS subject_file_raw_file_id_fkey"))
    op.execute(sa.text("ALTER TABLE subject_file DROP CONSTRAINT IF EXISTS uq_subject_file_user_subject_raw_file"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_subject_file_raw_file_id"))
    op.execute(sa.text("ALTER TABLE subject_file ADD COLUMN IF NOT EXISTS file_id VARCHAR"))
    op.execute(
        sa.text(
            """
            UPDATE subject_file AS subject_link
            SET file_id = mapping.file_id
            FROM atm_raw_file_id_map AS mapping
            WHERE subject_link.raw_file_id::text = mapping.old_id
              AND (subject_link.file_id IS NULL OR subject_link.file_id = '')
            """
        )
    )
    op.execute(sa.text("ALTER TABLE subject_file ALTER COLUMN file_id SET NOT NULL"))
    op.execute(
        sa.text(
            "ALTER TABLE subject_file DROP COLUMN IF EXISTS raw_file_id "
            "/* atm-allow-destructive-ddl: replaced by subject_file.file_id */"
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE subject_file
            ADD CONSTRAINT uq_subject_file_user_subject_file UNIQUE (user_id, subject, file_id)
            """
        )
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_subject_file_file_id ON subject_file (file_id)"))

    op.execute(sa.text("ALTER TABLE retrieval_chunk DROP CONSTRAINT IF EXISTS retrieval_chunk_document_id_fkey"))
    op.execute(sa.text("ALTER TABLE retrieval_chunk DROP CONSTRAINT IF EXISTS uq_retrieval_chunk_document_id_chunk_index"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_retrieval_chunk_document_id"))
    op.execute(sa.text("ALTER TABLE retrieval_chunk ADD COLUMN IF NOT EXISTS file_id VARCHAR"))
    op.execute(
        sa.text(
            """
            UPDATE retrieval_chunk AS chunk
            SET file_id = mapping.file_id
            FROM atm_raw_file_id_map AS mapping
            WHERE chunk.document_id::text = mapping.old_id
              AND (chunk.file_id IS NULL OR chunk.file_id = '')
            """
        )
    )
    op.execute(sa.text("ALTER TABLE retrieval_chunk ALTER COLUMN file_id SET NOT NULL"))
    op.execute(
        sa.text(
            "ALTER TABLE retrieval_chunk DROP COLUMN IF EXISTS document_id "
            "/* atm-allow-destructive-ddl: replaced by retrieval_chunk.file_id */"
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE retrieval_chunk
            ADD CONSTRAINT uq_retrieval_chunk_subject_file_id_chunk_index UNIQUE (subject, file_id, chunk_index)
            """
        )
    )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_retrieval_chunk_file_id ON retrieval_chunk (file_id)"))

    op.execute(sa.text("DROP INDEX IF EXISTS ix_raw_file_uid"))
    op.execute(sa.text("ALTER TABLE raw_file DROP CONSTRAINT IF EXISTS raw_file_pkey CASCADE"))
    op.execute(sa.text("ALTER TABLE raw_file ALTER COLUMN id DROP DEFAULT"))
    op.execute(
        sa.text(
            """
            ALTER TABLE raw_file
            ALTER COLUMN id TYPE VARCHAR
            USING COALESCE(NULLIF(uid, ''), 'file_' || md5(id::text))
            """
        )
    )
    op.execute(sa.text("ALTER TABLE raw_file ADD PRIMARY KEY (id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_raw_file_id ON raw_file (id)"))
    op.execute(
        sa.text(
            "ALTER TABLE raw_file DROP COLUMN IF EXISTS uid "
            "/* atm-allow-destructive-ddl: merged RawFile.uid into RawFile.id */"
        )
    )
    op.execute(sa.text("DROP SEQUENCE IF EXISTS raw_file_id_seq"))

    op.execute(
        sa.text(
            """
            ALTER TABLE subject_file
            ADD CONSTRAINT subject_file_file_id_fkey
            FOREIGN KEY (file_id) REFERENCES raw_file(id)
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE retrieval_chunk
            ADD CONSTRAINT retrieval_chunk_file_id_fkey
            FOREIGN KEY (file_id) REFERENCES raw_file(id)
            """
        )
    )


def downgrade() -> None:
    raise NotImplementedError("RawFile string ID migration is not reversible.")
