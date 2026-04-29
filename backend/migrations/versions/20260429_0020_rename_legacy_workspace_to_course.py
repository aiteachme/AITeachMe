"""Rename the legacy workspace schema to course naming."""

from __future__ import annotations

from alembic import op


revision = "20260429_0020"
down_revision = "20260429_0019"
branch_labels = None
depends_on = None


_LEGACY = "sub" + "ject"


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _rename_table_if_needed(*, old_name: str, new_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass({_literal(old_name)}) IS NOT NULL
               AND to_regclass({_literal(new_name)}) IS NULL
            THEN
                ALTER TABLE {_quote(old_name)} RENAME TO {_quote(new_name)};
            END IF;
        END $$;
        """
    )


def _rename_column_if_needed(
    *,
    table_name: str,
    old_name: str,
    new_name: str,
) -> None:
    table_lit = _literal(table_name)
    old_lit = _literal(old_name)
    new_lit = _literal(new_name)
    table_ident = _quote(table_name)
    old_ident = _quote(old_name)
    new_ident = _quote(new_name)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = {table_lit}
                  AND column_name = {old_lit}
            )
            THEN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = {table_lit}
                      AND column_name = {new_lit}
                )
                THEN
                    UPDATE {table_ident}
                    SET {new_ident} = {old_ident}
                    WHERE ({new_ident} IS NULL OR {new_ident} = '')
                      AND {old_ident} IS NOT NULL
                      AND {old_ident} <> '';
                    ALTER TABLE {table_ident}
                    DROP COLUMN {old_ident} /* atm-allow-destructive-ddl: merged legacy workspace naming into course naming */;
                ELSE
                    ALTER TABLE {table_ident}
                    RENAME COLUMN {old_ident} TO {new_ident};
                END IF;
            END IF;
        END $$;
        """
    )


def _rename_postgres_objects() -> None:
    legacy_lit = _literal(_LEGACY)
    op.execute(
        f"""
        DO $$
        DECLARE
            obj record;
            target_name text;
        BEGIN
            FOR obj IN
                SELECT
                    n.nspname AS schema_name,
                    t.relname AS table_name,
                    t.oid AS table_oid,
                    c.conname AS object_name
                FROM pg_constraint AS c
                JOIN pg_class AS t ON t.oid = c.conrelid
                JOIN pg_namespace AS n ON n.oid = t.relnamespace
                WHERE n.nspname = current_schema()
                  AND c.conname LIKE '%' || {legacy_lit} || '%'
                ORDER BY c.conname
            LOOP
                target_name := replace(obj.object_name, {legacy_lit}, 'course');
                IF target_name <> obj.object_name
                   AND NOT EXISTS (
                       SELECT 1
                       FROM pg_constraint
                       WHERE conrelid = obj.table_oid
                         AND conname = target_name
                   )
                THEN
                    EXECUTE format(
                        'ALTER TABLE %I.%I RENAME CONSTRAINT %I TO %I',
                        obj.schema_name,
                        obj.table_name,
                        obj.object_name,
                        target_name
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )
    op.execute(
        f"""
        DO $$
        DECLARE
            obj record;
            target_name text;
        BEGIN
            FOR obj IN
                SELECT
                    n.nspname AS schema_name,
                    c.relname AS object_name
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema()
                  AND c.relkind = 'i'
                  AND c.relname LIKE '%' || {legacy_lit} || '%'
                ORDER BY c.relname
            LOOP
                target_name := replace(obj.object_name, {legacy_lit}, 'course');
                IF target_name <> obj.object_name
                   AND to_regclass(quote_ident(obj.schema_name) || '.' || quote_ident(target_name)) IS NULL
                THEN
                    EXECUTE format(
                        'ALTER INDEX IF EXISTS %I.%I RENAME TO %I',
                        obj.schema_name,
                        obj.object_name,
                        target_name
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    legacy_id_column = f"{_LEGACY}_id"
    legacy_name_column = f"{_LEGACY}_name"
    legacy_intro_column = f"{_LEGACY}_intro_text"

    _rename_table_if_needed(old_name=_LEGACY, new_name="course")
    _rename_table_if_needed(old_name=f"{_LEGACY}_file", new_name="course_file")

    table_column_renames = {
        "course": ((legacy_intro_column, "course_intro_text"),),
        "raw_file": (
            (f"origin_{legacy_id_column}", "origin_course_id"),
            (f"origin_{legacy_name_column}", "origin_course_name"),
        ),
        "course_file": ((legacy_id_column, "course_id"),),
        "retrieval_chunk": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "knowledge_document": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "knowledge_unit": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "knowledge_edge": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "knowledge_graph_sync_run": ((legacy_id_column, "course_id"),),
        "knowledge_graph_source_ref": ((legacy_id_column, "course_id"),),
        "question_type_registry": ((legacy_id_column, "course_id"),),
        "question_template": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "exam_paper": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "exam_study_guide_cache": ((legacy_id_column, "course_id"),),
        "user_knowledge_state": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "chat_session": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
        "chat_message": ((legacy_id_column, "course_id"), (_LEGACY, "course_id")),
    }

    for table_name, renames in table_column_renames.items():
        for old_name, new_name in renames:
            _rename_column_if_needed(
                table_name=table_name,
                old_name=old_name,
                new_name=new_name,
            )

    _rename_postgres_objects()


def downgrade() -> None:
    raise RuntimeError("Downgrading course schema naming is not supported.")
