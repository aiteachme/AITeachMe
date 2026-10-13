"""One-time removal of retired question-type data and SQLite schema.

Only database upgrades use this module; no custom-type runtime is retained.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


REMOVED_COLUMNS = {
    "question_template": (
        "identity_hash", "question_type_registry_id", "question_type_version_id",
        "public_payload_json", "answer_schema_json", "reference_answer_json",
        "grading_spec_json", "runtime_snapshot_json", "profile_eligible",
    ),
    "exam_paper_item": (
        "question_type_registry_id", "question_type_version_id", "public_payload_snapshot_json",
        "answer_schema_snapshot_json", "reference_answer_snapshot_json", "grading_spec_snapshot_json",
        "runtime_snapshot_json", "profile_eligible", "answer_payload_json",
        "grading_detail_json", "grading_status", "grading_error_code",
    ),
    "mastery_drill_attempt": ("answer_payload_json", "grading_detail_json"),
    "question_type_registry": ("status",),
}
REMOVED_TABLES = (
    "question_type_package_asset", "question_type_package_import", "question_type_package_version",
)
_BUILTINS = "'single_choice', 'multiple_choice', 'multi_choice', 'true_false', 'fill_blank', 'short_answer'"
_DDL_MARKER = "/* atm-allow-destructive-ddl: remove retired question-type data and schema */"


def cleanup_statements(dialect: str, *, runtime_columns: bool = True) -> list[str]:
    """Use temporary ID sets so child deletion cannot change the parent selection."""
    custom_question = f"question_type NOT IN ({_BUILTINS})"
    if runtime_columns:
        custom_question += " OR question_type_version_id IS NOT NULL"
    if dialect == "postgresql":
        custom_config = f"""
            COALESCE(config_snapshot_json::jsonb -> 'question_type_runtimes', '[]'::jsonb)
                NOT IN ('[]'::jsonb, 'null'::jsonb, '{{}}'::jsonb)
            OR EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(
                    COALESCE(config_snapshot_json::jsonb -> 'question_types', '[]'::jsonb)
                ) AS type_key WHERE type_key NOT IN ({_BUILTINS})
            )"""
        consumed_paper = """EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
                COALESCE(stats_json::jsonb -> 'consumed_exam_paper_ids', '[]'::jsonb)
            ) AS paper_id WHERE paper_id IN (SELECT CAST(id AS TEXT) FROM _retired_papers)
        )"""
    else:
        custom_config = f"""
            COALESCE(json_extract(config_snapshot_json, '$.question_type_runtimes'), '[]') NOT IN ('[]', '{{}}')
            OR EXISTS (
                SELECT 1 FROM json_each(config_snapshot_json, '$.question_types')
                WHERE value NOT IN ({_BUILTINS})
            )"""
        consumed_paper = """EXISTS (
            SELECT 1 FROM json_each(stats_json, '$.consumed_exam_paper_ids')
            WHERE CAST(value AS INTEGER) IN (SELECT id FROM _retired_papers)
        )"""
    statements = [
        f"CREATE TEMPORARY TABLE _retired_templates AS SELECT id FROM question_template WHERE {custom_question}",
        f"""CREATE TEMPORARY TABLE _retired_papers AS SELECT id FROM exam_paper
            WHERE ({custom_config}) OR id IN (
                SELECT exam_paper_id FROM exam_paper_item WHERE {custom_question}
                OR question_template_id IN (SELECT id FROM _retired_templates)
            )""",
        """CREATE TEMPORARY TABLE _retired_items AS SELECT id FROM exam_paper_item
            WHERE exam_paper_id IN (SELECT id FROM _retired_papers)""",
        """CREATE TEMPORARY TABLE _retired_drills AS SELECT id FROM mastery_drill_session
            WHERE exam_paper_id IN (SELECT id FROM _retired_papers)""",
        f"""CREATE TEMPORARY TABLE _retired_states AS SELECT id, user_id, course_id FROM user_knowledge_state
            WHERE source_exam_paper_id IN (SELECT id FROM _retired_papers) OR {consumed_paper}""",
        """CREATE TEMPORARY TABLE _affected_profiles AS
            SELECT user_id, course_id FROM exam_paper WHERE id IN (SELECT id FROM _retired_papers)
            UNION SELECT user_id, course_id FROM _retired_states""",
        # Cached summaries also include exam history without mastery states.
        # Invalidate them even when no graded paper remains to trigger replay.
        """UPDATE course SET profile_json = '{}', updated_at = CURRENT_TIMESTAMP
            WHERE id IN (SELECT course_id FROM _affected_profiles)""",
        """UPDATE "user" SET profile_json = '{}', updated_at = CURRENT_TIMESTAMP
            WHERE id IN (SELECT user_id FROM _affected_profiles)""",
        """DELETE FROM mastery_drill_attempt WHERE mastery_drill_session_id IN (SELECT id FROM _retired_drills)
            OR exam_paper_item_id IN (SELECT id FROM _retired_items)
            OR question_template_id IN (SELECT id FROM _retired_templates)""",
        "DELETE FROM mastery_drill_session WHERE id IN (SELECT id FROM _retired_drills)",
        """DELETE FROM question_knowledge_unit_link WHERE exam_paper_item_id IN (SELECT id FROM _retired_items)
            OR question_template_id IN (SELECT id FROM _retired_templates)""",
        "DELETE FROM exam_study_guide_cache WHERE exam_paper_id IN (SELECT id FROM _retired_papers)",
        "DELETE FROM exam_profile_sync WHERE exam_paper_id IN (SELECT id FROM _retired_papers)",
        "UPDATE course_initial_exam_job SET exam_paper_id = NULL WHERE exam_paper_id IN (SELECT id FROM _retired_papers)",
        # Invalidated aggregates are rebuilt through the existing idempotent profile outbox.
        "DELETE FROM user_knowledge_state WHERE id IN (SELECT id FROM _retired_states)",
        "DELETE FROM exam_paper_item WHERE id IN (SELECT id FROM _retired_items)",
        "DELETE FROM exam_paper WHERE id IN (SELECT id FROM _retired_papers)",
        "DELETE FROM question_template WHERE id IN (SELECT id FROM _retired_templates)",
        """CREATE TEMPORARY TABLE _profile_replay_papers AS SELECT p.id, p.course_id, p.user_id
            FROM exam_paper p WHERE p.status = 'graded' AND EXISTS (
                SELECT 1 FROM _retired_states s WHERE s.course_id = p.course_id AND s.user_id = p.user_id
            )""",
        """UPDATE exam_profile_sync SET status = 'pending', attempt_count = 0, next_attempt_at = CURRENT_TIMESTAMP,
            claim_token = '', lease_expires_at = NULL, last_error_code = '', completed_at = NULL,
            updated_at = CURRENT_TIMESTAMP WHERE exam_paper_id IN (SELECT id FROM _profile_replay_papers)""",
        """INSERT INTO exam_profile_sync (
            exam_paper_id, course_id, user_id, status, trigger, attempt_count, manual_retry_count,
            next_attempt_at, claim_token, last_error_code, states_updated, review_task_count, created_at, updated_at
        ) SELECT p.id, p.course_id, p.user_id, 'pending', 'exam_graded', 0, 0,
            CURRENT_TIMESTAMP, '', '', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM _profile_replay_papers p WHERE NOT EXISTS (
                SELECT 1 FROM exam_profile_sync s WHERE s.exam_paper_id = p.id
            )""",
    ]
    return statements


def finish_cleanup_statements() -> list[str]:
    return [
        f"DELETE FROM question_type_registry WHERE type_key NOT IN ({_BUILTINS}) OR source = 'upload'",
        *[f"DROP TABLE {name} {_DDL_MARKER}" for name in (
            "_profile_replay_papers", "_affected_profiles", "_retired_states", "_retired_drills",
            "_retired_items", "_retired_papers", "_retired_templates",
        )],
    ]


def postgres_schema_statements() -> list[str]:
    return [
        *[f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column} {_DDL_MARKER}"
          for table, columns in REMOVED_COLUMNS.items() for column in columns],
        *[f"DROP TABLE IF EXISTS {table} {_DDL_MARKER}" for table in REMOVED_TABLES],
    ]


def migrate_sqlite_question_types(engine: sa.Engine) -> Path | None:
    """Back up and atomically purge one local database; repeat calls are no-ops."""
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    if not (tables.intersection(REMOVED_TABLES) or any(
        set(columns).intersection(column["name"] for column in inspector.get_columns(table))
        for table, columns in REMOVED_COLUMNS.items() if table in tables
    )):
        return None

    backup_path = None
    database = engine.url.database
    if database and database != ":memory:":
        source_path = Path(database).resolve()
        backup_path = source_path.parent / 'backups' / f'custom-type-cleanup-{datetime.now():%Y%m%d-%H%M%S-%f}.db'
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(backup_path) as destination:
                source.backup(destination)

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
        connection.commit()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            inspector = sa.inspect(connection)
            high_watermarks = {
                table: connection.exec_driver_sql(f'SELECT COALESCE(MAX(id), 0) FROM {table}').scalar_one()
                for table in ('question_template', 'exam_paper')
            }
            runtime_columns = 'question_type_version_id' in {c['name'] for c in inspector.get_columns('question_template')}
            for statement in cleanup_statements('sqlite', runtime_columns=runtime_columns):
                connection.exec_driver_sql(statement)
            operations = Operations(MigrationContext.configure(connection))
            for table, columns in {**REMOVED_COLUMNS, 'exam_paper': ()}.items():
                existing = {column['name'] for column in inspector.get_columns(table)}
                removed = existing.intersection(columns)
                if not removed and table not in high_watermarks:
                    continue
                naming = {'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'}
                table_kwargs = {'sqlite_autoincrement': True} if table in high_watermarks else {}
                with operations.batch_alter_table(table, recreate='always', naming_convention=naming, table_kwargs=table_kwargs) as batch:
                    for index in inspector.get_indexes(table):
                        if removed.intersection(index['column_names']):
                            batch.drop_index(index['name'])
                    for constraint in inspector.get_unique_constraints(table):
                        if removed.intersection(constraint['column_names']) and constraint['name']:
                            batch.drop_constraint(constraint['name'], type_='unique')
                    for foreign_key in inspector.get_foreign_keys(table):
                        if removed.intersection(foreign_key['constrained_columns']):
                            name = foreign_key['name'] or f"fk_{table}_{foreign_key['constrained_columns'][0]}_{foreign_key['referred_table']}"
                            batch.drop_constraint(name, type_='foreignkey')
                    for column in columns:
                        if column in removed:
                            batch.drop_column(column)
            # Old browser drafts and deep links use numeric IDs. Never reuse an
            # ID belonging to a deleted custom question or paper.
            for table, maximum in high_watermarks.items():
                connection.execute(sa.text('UPDATE sqlite_sequence SET seq = MAX(seq, :maximum) WHERE name = :table'),
                                   {'maximum': maximum, 'table': table})
                connection.execute(sa.text('INSERT INTO sqlite_sequence (name, seq) SELECT :table, :maximum '
                                           'WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = :table)'),
                                   {'maximum': maximum, 'table': table})
            for table in REMOVED_TABLES:
                connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{table}"')
            for statement in finish_cleanup_statements():
                connection.exec_driver_sql(statement)
            if connection.exec_driver_sql('PRAGMA foreign_key_check').fetchone() is not None:
                raise RuntimeError('Question-type cleanup would leave invalid foreign keys; transaction rolled back.')
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.exec_driver_sql('PRAGMA foreign_keys = ON')
            connection.commit()
    return backup_path
