"""Use opaque string ids as the course primary key."""

from __future__ import annotations

from alembic import op


revision = "20260428_0017"
down_revision = "20260428_0016"
branch_labels = None
depends_on = None


_COURSE_COLUMN_TABLES = (
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
    "course_file",
)

_COURSE_INDEX_RENAMES = (
    ("ix_course_file_course", "ix_course_file_course_id"),
    ("ix_knowledge_document_course", "ix_knowledge_document_course_id"),
    ("ix_knowledge_unit_course", "ix_knowledge_unit_course_id"),
    ("ix_retrieval_chunk_course", "ix_retrieval_chunk_course_id"),
    ("ix_knowledge_edge_course", "ix_knowledge_edge_course_id"),
    ("ix_question_template_course", "ix_question_template_course_id"),
    ("ix_exam_paper_course", "ix_exam_paper_course_id"),
    ("ix_user_knowledge_state_course", "ix_user_knowledge_state_course_id"),
    ("ix_chat_session_course", "ix_chat_session_course_id"),
    ("ix_chat_message_course", "ix_chat_message_course_id"),
    ("ix_question_type_registry_course", "ix_question_type_registry_course_id"),
    ("ix_knowledge_graph_sync_run_course", "ix_knowledge_graph_sync_run_course_id"),
    ("ix_knowledge_graph_source_ref_course", "ix_knowledge_graph_source_ref_course_id"),
    ("ix_exam_study_guide_cache_course", "ix_exam_study_guide_cache_course_id"),
)

_COURSE_FOREIGN_KEYS = (
    ("exam_paper", "course_id"),
    ("exam_study_guide_cache", "course_id"),
    ("knowledge_document", "course_id"),
    ("knowledge_unit", "course_id"),
    ("knowledge_edge", "course_id"),
    ("knowledge_graph_source_ref", "course_id"),
    ("knowledge_graph_sync_run", "course_id"),
    ("question_template", "course_id"),
    ("retrieval_chunk", "course_id"),
    ("course_file", "course_id"),
    ("user_knowledge_state", "course_id"),
)


def _drop_legacy_course_foreign_keys() -> None:
    op.execute("ALTER TABLE IF EXISTS retrieval_chunk DROP CONSTRAINT IF EXISTS retrieval_chunk_course_fkey")
    op.execute("ALTER TABLE IF EXISTS course_file DROP CONSTRAINT IF EXISTS course_file_course_fkey")


def _drop_legacy_course_indexes() -> None:
    for index_name, _new_name in _COURSE_INDEX_RENAMES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    op.execute("DROP INDEX IF EXISTS ix_raw_file_course")
    op.execute("DROP INDEX IF EXISTS ix_course_slug")


def _rename_course_columns() -> None:
    for table_name in _COURSE_COLUMN_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = '{table_name}'
                      AND column_name = 'course'
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = '{table_name}'
                      AND column_name = 'course_id'
                )
                THEN
                    ALTER TABLE {table_name} RENAME COLUMN course TO course_id;
                END IF;
            END $$;
            """
        )


def _migrate_raw_file_origin_course() -> None:
    op.execute("ALTER TABLE raw_file ADD COLUMN IF NOT EXISTS origin_course_id VARCHAR")
    op.execute("ALTER TABLE raw_file ADD COLUMN IF NOT EXISTS origin_course_name VARCHAR")
    op.execute(
        """
        UPDATE raw_file AS rf
        SET origin_course_id = s.slug,
            origin_course_name = s.name
        FROM course AS s
        WHERE rf.course IS NOT NULL
          AND rf.course <> ''
          AND rf.course = s.slug
          AND rf.origin_course_id IS NULL
        """
    )
    op.execute("ALTER TABLE raw_file DROP COLUMN IF EXISTS course /* atm-allow-destructive-ddl: replaced by origin_course_id/name and course_file links */")


def _migrate_course_primary_key() -> None:
    op.execute("ALTER TABLE course ADD COLUMN IF NOT EXISTS id_new VARCHAR")
    op.execute("UPDATE course SET id_new = slug WHERE id_new IS NULL")
    op.execute("ALTER TABLE course ALTER COLUMN id_new SET NOT NULL")
    op.execute("ALTER TABLE course DROP CONSTRAINT IF EXISTS course_pkey")
    op.execute("ALTER TABLE course DROP COLUMN IF EXISTS id /* atm-allow-destructive-ddl: replaced by string course.id from legacy slug */")
    op.execute("ALTER TABLE course RENAME COLUMN id_new TO id")
    op.execute("ALTER TABLE course ADD CONSTRAINT course_pkey PRIMARY KEY (id)")
    op.execute("ALTER TABLE course DROP COLUMN IF EXISTS slug /* atm-allow-destructive-ddl: merged into course.id */")


def _create_course_indexes() -> None:
    for _old_name, new_name in _COURSE_INDEX_RENAMES:
        table_name = new_name.removeprefix("ix_").removesuffix("_course_id")
        if table_name == "knowledge_graph_sync_run":
            table_name = "knowledge_graph_sync_run"
        elif table_name == "knowledge_graph_source_ref":
            table_name = "knowledge_graph_source_ref"
        elif table_name == "exam_study_guide_cache":
            table_name = "exam_study_guide_cache"
        op.execute(f"CREATE INDEX IF NOT EXISTS {new_name} ON {table_name} (course_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_file_origin_course_id ON raw_file (origin_course_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_raw_file_origin_course_name ON raw_file (origin_course_name)")


def _create_course_foreign_keys() -> None:
    for table_name, column_name in _COURSE_FOREIGN_KEYS:
        constraint_name = f"fk_{table_name}_{column_name}_course"
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ADD CONSTRAINT {constraint_name}
            FOREIGN KEY ({column_name}) REFERENCES course(id)
            """
        )


def upgrade() -> None:
    _drop_legacy_course_foreign_keys()
    _drop_legacy_course_indexes()
    _migrate_raw_file_origin_course()
    _rename_course_columns()
    _migrate_course_primary_key()
    _create_course_indexes()
    _create_course_foreign_keys()


def downgrade() -> None:
    raise RuntimeError("Downgrading the course string-primary-key migration is not supported.")
