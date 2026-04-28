"""Use subj_xxx as the subject primary key."""

from __future__ import annotations

from alembic import op


revision = "20260428_0017"
down_revision = "20260428_0016"
branch_labels = None
depends_on = None


_SUBJECT_COLUMN_TABLES = (
    "knowledge_document",
    "knowledge_unit",
    "retrieval_chunk",
    "knowledge_edge",
    "question_template",
    "exam_paper",
    "user_knowledge_state",
    "chat_session",
    "chat_message",
    "question_type_registry",
    "knowledge_graph_sync_run",
    "knowledge_graph_source_ref",
    "exam_study_guide_cache",
    "subject_file",
)

_SUBJECT_INDEX_RENAMES = (
    ("ix_subject_file_subject", "ix_subject_file_subject_id"),
    ("ix_knowledge_document_subject", "ix_knowledge_document_subject_id"),
    ("ix_knowledge_unit_subject", "ix_knowledge_unit_subject_id"),
    ("ix_retrieval_chunk_subject", "ix_retrieval_chunk_subject_id"),
    ("ix_knowledge_edge_subject", "ix_knowledge_edge_subject_id"),
    ("ix_question_template_subject", "ix_question_template_subject_id"),
    ("ix_exam_paper_subject", "ix_exam_paper_subject_id"),
    ("ix_user_knowledge_state_subject", "ix_user_knowledge_state_subject_id"),
    ("ix_chat_session_subject", "ix_chat_session_subject_id"),
    ("ix_chat_message_subject", "ix_chat_message_subject_id"),
    ("ix_question_type_registry_subject", "ix_question_type_registry_subject_id"),
    ("ix_knowledge_graph_sync_run_subject", "ix_knowledge_graph_sync_run_subject_id"),
    ("ix_knowledge_graph_source_ref_subject", "ix_knowledge_graph_source_ref_subject_id"),
    ("ix_exam_study_guide_cache_subject", "ix_exam_study_guide_cache_subject_id"),
)

_SUBJECT_FOREIGN_KEYS = (
    ("exam_paper", "subject_id"),
    ("exam_study_guide_cache", "subject_id"),
    ("knowledge_document", "subject_id"),
    ("knowledge_unit", "subject_id"),
    ("knowledge_edge", "subject_id"),
    ("knowledge_graph_source_ref", "subject_id"),
    ("knowledge_graph_sync_run", "subject_id"),
    ("question_template", "subject_id"),
    ("retrieval_chunk", "subject_id"),
    ("subject_file", "subject_id"),
    ("user_knowledge_state", "subject_id"),
)


def _drop_legacy_subject_foreign_keys() -> None:
    op.execute("ALTER TABLE IF EXISTS retrieval_chunk DROP CONSTRAINT IF EXISTS retrieval_chunk_subject_fkey")
    op.execute("ALTER TABLE IF EXISTS subject_file DROP CONSTRAINT IF EXISTS subject_file_subject_fkey")


def _drop_legacy_subject_indexes() -> None:
    for index_name, _new_name in _SUBJECT_INDEX_RENAMES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    op.execute("DROP INDEX IF EXISTS ix_raw_file_subject")
    op.execute("DROP INDEX IF EXISTS ix_subject_slug")


def _rename_subject_columns() -> None:
    for table_name in _SUBJECT_COLUMN_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = '{table_name}'
                      AND column_name = 'subject'
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = '{table_name}'
                      AND column_name = 'subject_id'
                )
                THEN
                    ALTER TABLE {table_name} RENAME COLUMN subject TO subject_id;
                END IF;
            END $$;
            """
        )


def _migrate_raw_file_origin_subject() -> None:
    op.execute("ALTER TABLE raw_file ADD COLUMN IF NOT EXISTS origin_subject_id VARCHAR")
    op.execute("ALTER TABLE raw_file ADD COLUMN IF NOT EXISTS origin_subject_name VARCHAR")
    op.execute(
        """
        UPDATE raw_file AS rf
        SET origin_subject_id = s.slug,
            origin_subject_name = s.name
        FROM subject AS s
        WHERE rf.subject IS NOT NULL
          AND rf.subject <> ''
          AND rf.subject = s.slug
          AND rf.origin_subject_id IS NULL
        """
    )
    op.execute("ALTER TABLE raw_file DROP COLUMN IF EXISTS subject /* atm-allow-destructive-ddl: replaced by origin_subject_id/name and subject_file links */")


def _migrate_subject_primary_key() -> None:
    op.execute("ALTER TABLE subject ADD COLUMN IF NOT EXISTS id_new VARCHAR")
    op.execute("UPDATE subject SET id_new = slug WHERE id_new IS NULL")
    op.execute("ALTER TABLE subject ALTER COLUMN id_new SET NOT NULL")
    op.execute("ALTER TABLE subject DROP CONSTRAINT IF EXISTS subject_pkey")
    op.execute("ALTER TABLE subject DROP COLUMN IF EXISTS id /* atm-allow-destructive-ddl: replaced by string subject.id from legacy slug */")
    op.execute("ALTER TABLE subject RENAME COLUMN id_new TO id")
    op.execute("ALTER TABLE subject ADD CONSTRAINT subject_pkey PRIMARY KEY (id)")
    op.execute("ALTER TABLE subject DROP COLUMN IF EXISTS slug /* atm-allow-destructive-ddl: merged into subject.id */")


def _create_subject_indexes() -> None:
    for _old_name, new_name in _SUBJECT_INDEX_RENAMES:
        table_name = new_name.removeprefix("ix_").removesuffix("_subject_id")
        if table_name == "knowledge_graph_sync_run":
            table_name = "knowledge_graph_sync_run"
        elif table_name == "knowledge_graph_source_ref":
            table_name = "knowledge_graph_source_ref"
        elif table_name == "exam_study_guide_cache":
            table_name = "exam_study_guide_cache"
        op.execute(f"CREATE INDEX IF NOT EXISTS {new_name} ON {table_name} (subject_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_file_origin_subject_id ON raw_file (origin_subject_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_file_origin_subject_name ON raw_file (origin_subject_name)")


def _create_subject_foreign_keys() -> None:
    for table_name, column_name in _SUBJECT_FOREIGN_KEYS:
        constraint_name = f"fk_{table_name}_{column_name}_subject"
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ADD CONSTRAINT {constraint_name}
            FOREIGN KEY ({column_name}) REFERENCES subject(id)
            """
        )


def upgrade() -> None:
    _drop_legacy_subject_foreign_keys()
    _drop_legacy_subject_indexes()
    _migrate_raw_file_origin_subject()
    _rename_subject_columns()
    _migrate_subject_primary_key()
    _create_subject_indexes()
    _create_subject_foreign_keys()


def downgrade() -> None:
    raise RuntimeError("Downgrading the subject string-primary-key migration is not supported.")
