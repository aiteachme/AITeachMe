"""Database bootstrap and session helpers."""

from __future__ import annotations

# Render 等平台预装 Python 未启用 SQLITE_ENABLE_LOAD_EXTENSION，
# pysqlite3-binary 自带完整功能，替换系统 sqlite3 即可。
try:
    import pysqlite3
    import sys
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Generator

import sqlalchemy as sa
import structlog
from sqlmodel import Session, SQLModel, create_engine, select

from app.shared.infra.settings import (
    clear_system_settings_override,
    get_settings,
    reset_project_settings_cache,
    set_system_settings_override,
    split_runtime_settings_payload,
)
from app.shared.infra.env_support import (
    describe_project_settings_source,
    get_env,
    get_env_bool,
    get_env_int,
    set_runtime_env_overrides,
)
from app.shared.infra.runtime import get_backend_root, is_cloud_mode, is_local_mode
from app.shared.infra.runtime import get_sqlite_db_path
from app.shared.infra.course import (
    extract_postgres_course_index_data_table_name,
)
from migrations.seed_data.question_types import BUILTIN_QUESTION_TYPE_ROWS
from app.models.chat import ChatMessage, ChatSession
from app.models.email_confirmation import EmailConfirmation
from app.models.exam import (
    ExamPaper,
    ExamPaperItem,
    ExamStudyGuideCache,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    QuestionTypeRegistry,
)
from app.models.knowledge import RetrievalChunk
from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_graph_sync import KnowledgeGraphSourceRef, KnowledgeGraphSyncRun
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.profile import UserKnowledgeState
from app.models.raw_file import RawFile, CourseFileLink
from app.models.chat import Highlight
from app.models.course import Course
from app.models.system import SystemRuntimeSettings
from app.models.user import User

logger = structlog.get_logger()

_engine = None
_SCHEMA_MODELS = (
    User,
    EmailConfirmation,
    Course,
    RawFile,
    CourseFileLink,
    RetrievalChunk,
    KnowledgeDocument,
    KnowledgeUnit,
    KnowledgeEdge,
    KnowledgeGraphSyncRun,
    KnowledgeGraphSourceRef,
    QuestionTypeRegistry,
    QuestionTemplate,
    ExamPaper,
    ExamPaperItem,
    QuestionKnowledgeUnitLink,
    ExamStudyGuideCache,
    UserKnowledgeState,
    ChatSession,
    ChatMessage,
    Highlight,
    SystemRuntimeSettings,
)
_SCHEMA_TABLES = [model.__table__ for model in _SCHEMA_MODELS]
_EXPECTED_SCHEMA_COLUMNS = {
    table.name: {column.name for column in table.columns}
    for table in _SCHEMA_TABLES
}
_ALLOWED_SQLITE_RUNTIME_TABLES = {
    "sqlite_sequence",
    # Memory keeps its own lightweight runtime tables for now. They are not
    # part of the SQLModel schema, but they are legitimate local app state and
    # must not trigger SQLite drift recovery.
    "memory_entries",
    "learning_logs",
}
_ALLOWED_SQLITE_RUNTIME_PREFIXES: tuple[str, ...] = (
    # sqlite-vec local vector tables and their shadow tables are runtime-owned.
    "atm_vec_",
)
_REMOVED_POSTGRES_TABLES = (
    "email_verification_code",
    "confirmed_build_plan",
    "system_settings_snapshot",
    "user_runtime_settings",
    "unit_dependency",
    "theme_tree_node",
    "taxonomy_anchor",
    "teaching_unit",
    "curriculum",
    "build_planner_turn",
    "build_planner_session",
)
_REMOVED_POSTGRES_COLUMNS = {
    "raw_file": ("uid",),
    "question_template": ("curriculum_version_id", "knowledge_unit_id", "knowledge_unit_refs_json"),
    "exam_paper": ("curriculum_version_id", "theme_tree_node_id"),
    "exam_paper_item": ("knowledge_unit_id", "knowledge_unit_refs_json"),
}
_REMOVED_SQLITE_TABLES = _REMOVED_POSTGRES_TABLES
_REMOVED_SQLITE_COLUMNS = {
    **{
        table_name: column_names
        for table_name, column_names in _REMOVED_POSTGRES_COLUMNS.items()
        if table_name != "raw_file"
    },
    "chat_session": ("user_goal",),
}
_SQLITE_ADDITIVE_COLUMNS = {
    "user": (
        ("runtime_settings_json", "JSON NOT NULL DEFAULT '{}'"),
    ),
    "course": (
        ("description", "TEXT NOT NULL DEFAULT ''"),
        ("user_intent", "TEXT NOT NULL DEFAULT ''"),
        ("learning_intent_text", "TEXT NOT NULL DEFAULT ''"),
        ("course_intro_text", "TEXT NOT NULL DEFAULT ''"),
        ("document_summary_json", "JSON NOT NULL DEFAULT '{}'"),
        ("llm_context_text", "TEXT NOT NULL DEFAULT ''"),
    ),
    "system_runtime_settings": (
        ("settings_source", "TEXT NOT NULL DEFAULT ''"),
        ("settings_hash", "TEXT NOT NULL DEFAULT ''"),
        ("effective_settings_json", "JSON NOT NULL DEFAULT '{}'"),
    ),
    "question_template": (
        ("is_marked", "BOOLEAN NOT NULL DEFAULT 0"),
    ),
    "exam_paper": (
        ("visibility", "TEXT NOT NULL DEFAULT 'visible'"),
        ("generation_origin", "TEXT NOT NULL DEFAULT 'user'"),
        ("config_hash", "TEXT NOT NULL DEFAULT ''"),
        ("config_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("prepared_at", "DATETIME NULL"),
        ("claimed_at", "DATETIME NULL"),
        ("expires_at", "DATETIME NULL"),
    ),
    "raw_file": (
        ("parse_request_signature", "TEXT NOT NULL DEFAULT 'default'"),
    ),
    "chat_session": (
        ("library_file_id", "TEXT NULL"),
    ),
    "highlight": (
        ("description", "TEXT NULL"),
        ("interactive_html", "TEXT NULL"),
        ("segments_json", "JSON NULL"),
    ),
}
_SQLITE_ADDITIVE_INDEXES = {
    "raw_file": (
        (
            "ix_raw_file_user_hash_size_type",
            ("user_id", "content_hash", "file_size_bytes", "filetype"),
            False,
            "",
        ),
        (
            "uq_raw_file_user_hash_size_type_signature_active",
            ("user_id", "content_hash", "file_size_bytes", "filetype", "parse_request_signature"),
            True,
            "status != 'failed' AND content_hash IS NOT NULL AND file_size_bytes IS NOT NULL",
        ),
    ),
}
_LEGACY_COURSE_TOKEN = "sub" + "ject"


def _legacy_course_name(suffix: str = "") -> str:
    return f"{_LEGACY_COURSE_TOKEN}{suffix}"


def _get_db_path():
    return get_sqlite_db_path()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str) -> object:
    return json.loads(value)


def reset_runtime_state() -> None:
    """Reset runtime singletons before rebuilding the local SQLite database.

    Schema drift recovery deletes the SQLite files and immediately recreates the
    engine. On Windows, the old engine must be disposed first or the file can
    stay locked. We also clear in-memory settings/search caches so rebuilt
    startup does not reuse state derived from the old database.
    """

    global _engine

    stale_engine = _engine
    _engine = None
    if stale_engine is not None:
        try:
            stale_engine.dispose()
        except Exception as exc:  # pragma: no cover - defensive cleanup only
            logger.warning("database_engine_dispose_failed_during_reset", error=str(exc))

    reset_project_settings_cache()
    clear_system_settings_override()

    from app.shared.infra.search import reset_search_runtime_caches

    reset_search_runtime_caches()
    logger.info("runtime_state_reset_for_local_db_rebuild")


def _is_allowed_runtime_table(table_name: str) -> bool:
    if table_name in _ALLOWED_SQLITE_RUNTIME_TABLES:
        return True
    return table_name.startswith(_ALLOWED_SQLITE_RUNTIME_PREFIXES)


def _inspect_sqlite_schema_drift(engine: sa.Engine) -> dict[str, object] | None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return None

    unexpected_tables = sorted(
        table_name
        for table_name in existing_tables
        if table_name not in _EXPECTED_SCHEMA_COLUMNS
        and not _is_allowed_runtime_table(table_name)
    )
    missing_columns: dict[str, list[str]] = {}
    unexpected_columns: dict[str, list[str]] = {}
    for table_name, expected_columns in _EXPECTED_SCHEMA_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {
            column["name"]
            for column in inspector.get_columns(table_name)
        }
        missing = sorted(expected_columns - existing_columns)
        unexpected = sorted(existing_columns - expected_columns)
        if missing:
            missing_columns[table_name] = missing
        if unexpected:
            unexpected_columns[table_name] = unexpected

    if not unexpected_tables and not missing_columns and not unexpected_columns:
        return None

    return {
        "unexpected_tables": unexpected_tables,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
    }


def _sqlite_file_paths(db_path: Path) -> tuple[Path, ...]:
    return tuple(Path(f"{db_path}{suffix}") for suffix in ("", "-shm", "-wal"))


def _backup_sqlite_files_before_rebuild(db_path: Path) -> Path | None:
    existing_paths = [path for path in _sqlite_file_paths(db_path) if path.exists()]
    if not existing_paths:
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = db_path.parent / "backups"
    backup_dir = backup_root / f"{db_path.name}.schema-drift.{timestamp}"
    counter = 1
    while backup_dir.exists():
        counter += 1
        backup_dir = backup_root / f"{db_path.name}.schema-drift.{timestamp}.{counter}"

    backup_dir.mkdir(parents=True, exist_ok=False)
    try:
        for path in existing_paths:
            shutil.copy2(path, backup_dir / path.name)
    except Exception:
        logger.exception(
            "local_sqlite_database_backup_failed",
            db_path=str(db_path),
            backup_dir=str(backup_dir),
        )
        raise

    logger.warning(
        "local_sqlite_database_backup_created",
        db_path=str(db_path),
        backup_dir=str(backup_dir),
    )
    return backup_dir


def _remove_sqlite_files(db_path: Path) -> None:
    for path in _sqlite_file_paths(db_path):
        path.unlink(missing_ok=True)


def _drop_sqlite_indexes_for_columns(
    connection: sa.Connection,
    inspector: sa.Inspector,
    *,
    table_name: str,
    column_names: set[str],
) -> None:
    for index in inspector.get_indexes(table_name):
        indexed_columns = set(index.get("column_names") or ())
        index_name = index.get("name")
        if not index_name or indexed_columns.isdisjoint(column_names):
            continue
        connection.execute(
            sa.text(
                f"DROP INDEX IF EXISTS {quote_sqlite_identifier(index_name)}"
            )
        )


def _normalize_legacy_question_refs(raw_refs: object, fallback_unit_id: object = None) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    if isinstance(raw_refs, str) and raw_refs.strip():
        try:
            decoded = json.loads(raw_refs)
        except json.JSONDecodeError:
            decoded = []
        if isinstance(decoded, list):
            refs.extend(item for item in decoded if isinstance(item, dict))

    if not refs and fallback_unit_id is not None:
        try:
            unit_id = int(fallback_unit_id or 0)
        except (TypeError, ValueError):
            unit_id = 0
        if unit_id > 0:
            refs.append({"knowledge_unit_id": unit_id, "coverage_weight": 1.0})

    normalized: list[dict[str, object]] = []
    seen: set[int] = set()
    for ref in refs:
        try:
            unit_id = int(ref.get("knowledge_unit_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if unit_id <= 0 or unit_id in seen:
            continue
        seen.add(unit_id)
        try:
            weight = float(ref.get("coverage_weight", 1.0) or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        normalized.append(
            {
                "knowledge_unit_id": unit_id,
                "coverage_weight": max(0.0, min(weight, 1.0)),
            }
        )
    return normalized


def _migrate_sqlite_question_knowledge_links(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not {"question_template", "exam_paper_item"} & existing_tables:
        return

    with engine.begin() as connection:
        QuestionKnowledgeUnitLink.__table__.create(connection, checkfirst=True)

        if "question_template" in existing_tables:
            template_columns = {column["name"] for column in inspector.get_columns("question_template")}
            if {"id"} <= template_columns and (
                "knowledge_unit_refs_json" in template_columns or "knowledge_unit_id" in template_columns
            ):
                select_columns = ["id"]
                select_columns.append("knowledge_unit_refs_json" if "knowledge_unit_refs_json" in template_columns else "NULL AS knowledge_unit_refs_json")
                select_columns.append("knowledge_unit_id" if "knowledge_unit_id" in template_columns else "NULL AS knowledge_unit_id")
                rows = connection.execute(sa.text(f"SELECT {', '.join(select_columns)} FROM question_template")).mappings()
                for row in rows:
                    for ref in _normalize_legacy_question_refs(row["knowledge_unit_refs_json"], row["knowledge_unit_id"]):
                        connection.execute(
                            sa.text(
                                """
                                INSERT OR IGNORE INTO question_knowledge_unit_link
                                (question_template_id, exam_paper_item_id, knowledge_unit_id, coverage_weight, created_at, updated_at)
                                VALUES (:template_id, NULL, :unit_id, :weight, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                """
                            ),
                            {
                                "template_id": int(row["id"]),
                                "unit_id": int(ref["knowledge_unit_id"]),
                                "weight": float(ref["coverage_weight"]),
                            },
                        )

        if "exam_paper_item" in existing_tables:
            item_columns = {column["name"] for column in inspector.get_columns("exam_paper_item")}
            if {"id"} <= item_columns and (
                "knowledge_unit_refs_json" in item_columns or "knowledge_unit_id" in item_columns
            ):
                select_columns = ["id"]
                select_columns.append("knowledge_unit_refs_json" if "knowledge_unit_refs_json" in item_columns else "NULL AS knowledge_unit_refs_json")
                select_columns.append("knowledge_unit_id" if "knowledge_unit_id" in item_columns else "NULL AS knowledge_unit_id")
                rows = connection.execute(sa.text(f"SELECT {', '.join(select_columns)} FROM exam_paper_item")).mappings()
                for row in rows:
                    for ref in _normalize_legacy_question_refs(row["knowledge_unit_refs_json"], row["knowledge_unit_id"]):
                        connection.execute(
                            sa.text(
                                """
                                INSERT OR IGNORE INTO question_knowledge_unit_link
                                (question_template_id, exam_paper_item_id, knowledge_unit_id, coverage_weight, created_at, updated_at)
                                VALUES (NULL, :item_id, :unit_id, :weight, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                """
                            ),
                            {
                                "item_id": int(row["id"]),
                                "unit_id": int(ref["knowledge_unit_id"]),
                                "weight": float(ref["coverage_weight"]),
                            },
                        )

        link_columns = {column["name"] for column in sa.inspect(connection).get_columns("question_knowledge_unit_link")}
        if "role" in link_columns:
            try:
                connection.execute(sa.text("ALTER TABLE question_knowledge_unit_link DROP COLUMN role"))
            except sa.exc.DatabaseError:
                logger.warning("sqlite_drop_question_link_role_column_failed")


def _sqlite_json_object_text(raw_value: object) -> str:
    return _json_dumps(_sqlite_json_object(raw_value))


def _sqlite_json_value(raw_value: object, fallback: object) -> object:
    if isinstance(raw_value, str):
        try:
            return json.loads(raw_value or _json_dumps(fallback))
        except json.JSONDecodeError:
            return fallback
    if raw_value is None:
        return fallback
    return raw_value


def _sqlite_json_object(raw_value: object) -> dict[str, object]:
    decoded = _sqlite_json_value(raw_value, {})
    return dict(decoded) if isinstance(decoded, dict) else {}


def _sqlite_json_list(raw_value: object) -> list[object]:
    decoded = _sqlite_json_value(raw_value, [])
    return list(decoded) if isinstance(decoded, list) else []


def _add_sqlite_column_if_missing(
    connection: sa.Connection,
    inspector: sa.Inspector,
    *,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    existing_columns = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }
    if column_name in existing_columns:
        return
    connection.execute(
        sa.text(
            f"ALTER TABLE {quote_sqlite_identifier(table_name)} "
            f"ADD COLUMN {quote_sqlite_identifier(column_name)} {column_sql}"
        )
    )


def _sqlite_table_names(connection: sa.Connection) -> set[str]:
    return set(sa.inspect(connection).get_table_names())


def _sqlite_column_names(connection: sa.Connection, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(connection).get_columns(table_name)
    }


def _rename_sqlite_table_if_needed(connection: sa.Connection, *, old_name: str, new_name: str) -> None:
    existing_tables = _sqlite_table_names(connection)
    if old_name not in existing_tables or new_name in existing_tables:
        return
    connection.execute(
        sa.text(
            f"ALTER TABLE {quote_sqlite_identifier(old_name)} "
            f"RENAME TO {quote_sqlite_identifier(new_name)}"
        )
    )
    logger.info("sqlite_table_renamed_for_course_schema", old_name=old_name, new_name=new_name)


def _rename_sqlite_column_if_needed(
    connection: sa.Connection,
    *,
    table_name: str,
    old_name: str,
    new_name: str,
) -> None:
    if table_name not in _sqlite_table_names(connection):
        return
    existing_columns = _sqlite_column_names(connection, table_name)
    if old_name not in existing_columns:
        return
    if new_name in existing_columns:
        connection.execute(
            sa.text(
                f"UPDATE {quote_sqlite_identifier(table_name)} "
                f"SET {quote_sqlite_identifier(new_name)} = {quote_sqlite_identifier(old_name)} "
                f"WHERE ({quote_sqlite_identifier(new_name)} IS NULL OR {quote_sqlite_identifier(new_name)} = '') "
                f"AND {quote_sqlite_identifier(old_name)} IS NOT NULL "
                f"AND {quote_sqlite_identifier(old_name)} != ''"
            )
        )
        _drop_sqlite_indexes_for_columns(
            connection,
            sa.inspect(connection),
            table_name=table_name,
            column_names={old_name},
        )
        try:
            connection.execute(
                sa.text(
                    f"ALTER TABLE {quote_sqlite_identifier(table_name)} "
                    f"DROP COLUMN {quote_sqlite_identifier(old_name)}"
                )
            )
            logger.info(
                "sqlite_legacy_column_dropped_for_course_schema",
                table_name=table_name,
                old_name=old_name,
                new_name=new_name,
            )
        except sa.exc.DatabaseError:
            logger.warning(
                "sqlite_legacy_column_drop_failed_for_course_schema",
                table_name=table_name,
                old_name=old_name,
                new_name=new_name,
            )
        return
    connection.execute(
        sa.text(
            f"ALTER TABLE {quote_sqlite_identifier(table_name)} "
            f"RENAME COLUMN {quote_sqlite_identifier(old_name)} "
            f"TO {quote_sqlite_identifier(new_name)}"
        )
    )
    logger.info(
        "sqlite_column_renamed_for_course_schema",
        table_name=table_name,
        old_name=old_name,
        new_name=new_name,
    )


def _migrate_sqlite_course_schema(engine: sa.Engine) -> None:
    """Rename the pre-course workspace schema in local SQLite databases."""

    legacy_table = _legacy_course_name()
    legacy_link_table = _legacy_course_name("_file")
    legacy_id_column = _legacy_course_name("_id")
    legacy_name_column = _legacy_course_name("_name")
    legacy_intro_column = _legacy_course_name("_intro_text")

    table_column_renames = {
        "course": ((legacy_intro_column, "course_intro_text"),),
        "raw_file": (
            (f"origin_{legacy_id_column}", "origin_course_id"),
            (f"origin_{legacy_name_column}", "origin_course_name"),
        ),
        "course_file": ((legacy_id_column, "course_id"),),
        "retrieval_chunk": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "knowledge_document": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "knowledge_unit": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "knowledge_edge": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "knowledge_graph_sync_run": ((legacy_id_column, "course_id"),),
        "knowledge_graph_source_ref": ((legacy_id_column, "course_id"),),
        "question_type_registry": ((legacy_id_column, "course_id"),),
        "question_template": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "exam_paper": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "exam_study_guide_cache": ((legacy_id_column, "course_id"),),
        "user_knowledge_state": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "chat_session": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
        "chat_message": ((legacy_id_column, "course_id"), (_legacy_course_name(), "course_id")),
    }

    with engine.begin() as connection:
        _rename_sqlite_table_if_needed(connection, old_name=legacy_table, new_name="course")
        _rename_sqlite_table_if_needed(connection, old_name=legacy_link_table, new_name="course_file")
        for table_name, renames in table_column_renames.items():
            for old_name, new_name in renames:
                _rename_sqlite_column_if_needed(
                    connection,
                    table_name=table_name,
                    old_name=old_name,
                    new_name=new_name,
                )


def _migrate_sqlite_email_confirmation(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "email_verification_code" not in existing_tables or "email_confirmation" in existing_tables:
        return

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "ALTER TABLE "
                f"{quote_sqlite_identifier('email_verification_code')} "
                f"RENAME TO {quote_sqlite_identifier('email_confirmation')}"
            )
        )


def _migrate_sqlite_user_runtime_settings(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "user" not in existing_tables or "user_runtime_settings" not in existing_tables:
        return

    with engine.begin() as connection:
        _add_sqlite_column_if_missing(
            connection,
            inspector,
            table_name="user",
            column_name="runtime_settings_json",
            column_sql="JSON NOT NULL DEFAULT '{}'",
        )
        rows = connection.execute(
            sa.text("SELECT user_id, settings_json FROM user_runtime_settings")
        ).mappings()
        for row in rows:
            user_id = str(row.get("user_id") or "").strip()
            if not user_id:
                continue
            connection.execute(
                sa.text(
                    f"UPDATE {quote_sqlite_identifier('user')} "
                    "SET runtime_settings_json = :settings_json "
                    "WHERE id = :user_id"
                ),
                {
                    "settings_json": _sqlite_json_object_text(row.get("settings_json")),
                    "user_id": user_id,
                },
            )


def _migrate_sqlite_system_settings_snapshot(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "system_runtime_settings" not in existing_tables or "system_settings_snapshot" not in existing_tables:
        return

    snapshot_columns = {
        column["name"]
        for column in inspector.get_columns("system_settings_snapshot")
    }
    if not snapshot_columns:
        return

    source_expr = "settings_source" if "settings_source" in snapshot_columns else "'' AS settings_source"
    hash_expr = "settings_hash" if "settings_hash" in snapshot_columns else "'' AS settings_hash"
    json_expr = "settings_json" if "settings_json" in snapshot_columns else "'{}' AS settings_json"

    with engine.begin() as connection:
        _add_sqlite_column_if_missing(
            connection,
            inspector,
            table_name="system_runtime_settings",
            column_name="settings_source",
            column_sql="TEXT NOT NULL DEFAULT ''",
        )
        _add_sqlite_column_if_missing(
            connection,
            inspector,
            table_name="system_runtime_settings",
            column_name="settings_hash",
            column_sql="TEXT NOT NULL DEFAULT ''",
        )
        _add_sqlite_column_if_missing(
            connection,
            inspector,
            table_name="system_runtime_settings",
            column_name="effective_settings_json",
            column_sql="JSON NOT NULL DEFAULT '{}'",
        )
        connection.execute(
            sa.text(
                """
                INSERT OR IGNORE INTO system_runtime_settings
                (id, settings_json, settings_source, settings_hash, effective_settings_json, created_at, updated_at)
                VALUES ('runtime', '{}', '', '', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        snapshot = connection.execute(
            sa.text(
                f"""
                SELECT {source_expr}, {hash_expr}, {json_expr}
                FROM system_settings_snapshot
                ORDER BY CASE WHEN id = 'runtime' THEN 0 ELSE 1 END
                LIMIT 1
                """
            )
        ).mappings().first()
        if snapshot is None:
            return
        connection.execute(
            sa.text(
                """
                UPDATE system_runtime_settings
                SET settings_source = :settings_source,
                    settings_hash = :settings_hash,
                    effective_settings_json = :effective_settings_json,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 'runtime'
                """
            ),
            {
                "settings_source": str(snapshot.get("settings_source") or ""),
                "settings_hash": str(snapshot.get("settings_hash") or ""),
                "effective_settings_json": _sqlite_json_object_text(snapshot.get("settings_json")),
            },
        )


def _migrate_sqlite_confirmed_build_plans(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "confirmed_build_plan" not in existing_tables or "chat_session" not in existing_tables:
        return
    plan_columns = {column["name"] for column in inspector.get_columns("confirmed_build_plan")}
    chat_columns = {column["name"] for column in inspector.get_columns("chat_session")}
    plan_course_column = "course_id" if "course_id" in plan_columns else "course" if "course" in plan_columns else None
    chat_course_column = "course_id" if "course_id" in chat_columns else "course" if "course" in chat_columns else None
    if plan_course_column is None or chat_course_column is None:
        return

    with engine.begin() as connection:
        plan_rows = list(
            connection.execute(
                sa.text(
                    f"""
                    SELECT id, {plan_course_column} AS course_id, planner_session_id, user_id, status, user_prompt,
                           digest_mode, selected_file_ids_json, chapter_plan_json,
                           build_constraints_json, plan_summary, plan_json,
                           created_at, updated_at
                    FROM confirmed_build_plan
                    WHERE planner_session_id IS NOT NULL
                      AND planner_session_id <> ''
                    """
                )
            ).mappings()
        )
        for row in plan_rows:
            session_row = connection.execute(
                sa.text(
                    f"""
                    SELECT meta_json
                    FROM chat_session
                    WHERE id = :session_id
                      AND {chat_course_column} = :course_id
                      AND user_id = :user_id
                      AND source = 'build_planner'
                    """
                ),
                {
                    "session_id": row.get("planner_session_id"),
                    "course_id": row.get("course_id"),
                    "user_id": row.get("user_id"),
                },
            ).mappings().first()
            if session_row is None:
                continue
            meta = _sqlite_json_object(session_row.get("meta_json"))
            raw_plan_json = _sqlite_json_object(row.get("plan_json"))
            confirmed_chapters = list(raw_plan_json.get("chapters") or _sqlite_json_list(row.get("chapter_plan_json")))
            confirmed_plan_text = str(raw_plan_json.get("plan") or row.get("plan_summary") or "")
            plan_payload = {
                "id": row.get("id"),
                "course_id": row.get("course_id"),
                "planner_session_id": row.get("planner_session_id"),
                "user_id": row.get("user_id"),
                "status": row.get("status") or "confirmed",
                "user_prompt": row.get("user_prompt") or "",
                "digest_mode": row.get("digest_mode") or "",
                "selected_file_ids": _sqlite_json_list(row.get("selected_file_ids_json")),
                "chapters": confirmed_chapters,
                "build_constraints": _sqlite_json_object(row.get("build_constraints_json")),
                "plan": confirmed_plan_text,
                "plan_json": {**raw_plan_json, "chapters": confirmed_chapters, "plan": confirmed_plan_text},
                "created_at": str(row.get("created_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            }
            meta["confirmed_plan_id"] = row.get("id")
            meta["confirmed_plan"] = plan_payload
            connection.execute(
                sa.text(
                    """
                    UPDATE chat_session
                    SET meta_json = :meta_json,
                        updated_at = CASE
                            WHEN :updated_at IS NOT NULL AND (:updated_at > updated_at OR updated_at IS NULL)
                            THEN :updated_at
                            ELSE updated_at
                        END,
                        last_message_at = CASE
                            WHEN :updated_at IS NOT NULL AND (:updated_at > last_message_at OR last_message_at IS NULL)
                            THEN :updated_at
                            ELSE last_message_at
                        END
                    WHERE id = :session_id
                    """
                ),
                {
                    "meta_json": _json_dumps(meta),
                    "updated_at": row.get("updated_at"),
                    "session_id": row.get("planner_session_id"),
                },
            )


def _drop_sqlite_removed_schema(engine: sa.Engine) -> None:
    _migrate_sqlite_question_knowledge_links(engine)
    _migrate_sqlite_email_confirmation(engine)
    _migrate_sqlite_confirmed_build_plans(engine)
    _migrate_sqlite_user_runtime_settings(engine)
    _migrate_sqlite_system_settings_snapshot(engine)
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = OFF"))
        try:
            for table_name, column_names in _REMOVED_SQLITE_COLUMNS.items():
                if table_name not in existing_tables:
                    continue
                existing_columns = {
                    column["name"]
                    for column in inspector.get_columns(table_name)
                }
                removed_columns = {
                    column_name
                    for column_name in column_names
                    if column_name in existing_columns
                }
                if removed_columns:
                    _drop_sqlite_indexes_for_columns(
                        connection,
                        inspector,
                        table_name=table_name,
                        column_names=removed_columns,
                    )
                for column_name in column_names:
                    if column_name not in existing_columns:
                        continue
                    try:
                        connection.execute(
                            sa.text(
                                f"ALTER TABLE {quote_sqlite_identifier(table_name)} "
                                f"DROP COLUMN {quote_sqlite_identifier(column_name)}"
                            )
                        )
                    except Exception as exc:
                        logger.warning(
                            "sqlite_legacy_column_drop_failed",
                            table_name=table_name,
                            column_name=column_name,
                            error=str(exc),
                        )

            for table_name in _REMOVED_SQLITE_TABLES:
                if table_name in existing_tables:
                    try:
                        connection.execute(
                            sa.text(f"DROP TABLE IF EXISTS {quote_sqlite_identifier(table_name)}")
                        )
                    except Exception as exc:
                        logger.warning(
                            "sqlite_legacy_table_drop_failed",
                            table_name=table_name,
                            error=str(exc),
                        )
        finally:
            connection.execute(sa.text("PRAGMA foreign_keys = ON"))


def _apply_sqlite_additive_schema_updates(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    with engine.begin() as connection:
        for table_name, columns in _SQLITE_ADDITIVE_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            for column_name, column_sql in columns:
                if column_name in existing_columns:
                    continue
                connection.execute(
                    sa.text(
                        f"ALTER TABLE {quote_sqlite_identifier(table_name)} "
                        f"ADD COLUMN {quote_sqlite_identifier(column_name)} {column_sql}"
                    )
                )
                existing_columns.add(column_name)
                logger.info(
                    "sqlite_additive_column_added",
                    table_name=table_name,
                    column_name=column_name,
                )


def _create_sqlite_missing_schema_tables(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = [
        table
        for table in _SCHEMA_TABLES
        if table.name not in existing_tables
    ]
    if not missing_tables:
        return
    with engine.begin() as connection:
        SQLModel.metadata.create_all(connection, tables=missing_tables)
    logger.info(
        "sqlite_missing_schema_tables_created",
        tables=[table.name for table in missing_tables],
    )


def _backfill_sqlite_raw_file_parse_signatures(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    if "raw_file" not in set(inspector.get_table_names()):
        return
    existing_columns = {
        column["name"]
        for column in inspector.get_columns("raw_file")
    }
    required_columns = {
        "id",
        "user_id",
        "content_hash",
        "file_size_bytes",
        "filetype",
        "status",
        "created_at",
        "parse_request_signature",
    }
    missing_columns = required_columns - existing_columns
    if missing_columns:
        logger.warning(
            "sqlite_raw_file_parse_signature_backfill_skipped",
            missing_columns=sorted(missing_columns),
        )
        return
    if "parse_request_signature" not in existing_columns:
        return

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "UPDATE raw_file SET parse_request_signature = 'default' "
                "WHERE parse_request_signature IS NULL OR parse_request_signature = ''"
            )
        )
        rows = connection.execute(
            sa.text(
                "SELECT id, user_id, content_hash, file_size_bytes, filetype "
                "FROM raw_file "
                "WHERE status != 'failed' "
                "AND content_hash IS NOT NULL "
                "AND file_size_bytes IS NOT NULL "
                "AND parse_request_signature = 'default' "
                "ORDER BY created_at ASC, id ASC"
            )
        ).mappings()
        seen: set[tuple[object, object, object, object]] = set()
        duplicate_ids: list[str] = []
        for row in rows:
            key = (row["user_id"], row["content_hash"], row["file_size_bytes"], row["filetype"])
            if key in seen:
                duplicate_ids.append(str(row["id"]))
            else:
                seen.add(key)
        for raw_file_id in duplicate_ids:
            connection.execute(
                sa.text(
                    "UPDATE raw_file SET parse_request_signature = :signature WHERE id = :raw_file_id"
                ),
                {"signature": f"legacy:{raw_file_id}", "raw_file_id": raw_file_id},
            )


def _backfill_sqlite_library_chat_sessions(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "chat_session" not in existing_tables:
        return

    chat_session_columns = {
        column["name"]
        for column in inspector.get_columns("chat_session")
    }
    if not {"source", "library_file_id"} <= chat_session_columns:
        return

    prefix = "library_selection:"
    source_like = f"{prefix}%"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                UPDATE chat_session
                SET library_file_id = substr(source, :start_index)
                WHERE (library_file_id IS NULL OR library_file_id = '')
                AND source LIKE :source_like
                AND length(source) >= :min_length
                """
            ),
            {
                "start_index": len(prefix) + 1,
                "source_like": source_like,
                "min_length": len(prefix) + 1,
            },
        )
        if "course_id" in chat_session_columns:
            connection.execute(
                sa.text(
                    """
                    UPDATE chat_session
                    SET course_id = ''
                    WHERE course_id = 'global'
                    AND source LIKE :source_like
                    """
                ),
                {"source_like": source_like},
            )

        if "chat_message" not in existing_tables:
            return
        chat_message_columns = {
            column["name"]
            for column in inspector.get_columns("chat_message")
        }
        if {"course_id", "source"} <= chat_message_columns:
            connection.execute(
                sa.text(
                    """
                    UPDATE chat_message
                    SET course_id = ''
                    WHERE course_id = 'global'
                    AND source LIKE :source_like
                    """
                ),
                {"source_like": source_like},
            )


def _apply_sqlite_additive_index_updates(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    with engine.begin() as connection:
        for table_name, indexes in _SQLITE_ADDITIVE_INDEXES.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            existing_index_names = {
                str(index.get("name") or "")
                for index in inspector.get_indexes(table_name)
            }
            for index_name, column_names, unique, where_clause in indexes:
                if index_name in existing_index_names:
                    continue
                missing_columns = set(column_names) - existing_columns
                if missing_columns:
                    logger.warning(
                        "sqlite_additive_index_skipped_missing_columns",
                        table_name=table_name,
                        index_name=index_name,
                        missing_columns=sorted(missing_columns),
                    )
                    continue
                columns_sql = ", ".join(
                    quote_sqlite_identifier(column_name)
                    for column_name in column_names
                )
                unique_sql = "UNIQUE " if unique else ""
                where_sql = f" WHERE {where_clause}" if where_clause else ""
                connection.execute(
                    sa.text(
                        f"CREATE {unique_sql}INDEX IF NOT EXISTS {quote_sqlite_identifier(index_name)} "
                        f"ON {quote_sqlite_identifier(table_name)} ({columns_sql}){where_sql}"
                    )
                )
                existing_index_names.add(index_name)
                logger.info(
                    "sqlite_additive_index_added",
                    table_name=table_name,
                    index_name=index_name,
                )


def _ensure_local_sqlite_schema(engine: sa.Engine) -> sa.Engine:
    db_path = _get_db_path()
    if not db_path.exists():
        return engine

    _migrate_sqlite_course_schema(engine)
    _drop_sqlite_removed_schema(engine)
    _create_sqlite_missing_schema_tables(engine)
    _apply_sqlite_additive_schema_updates(engine)
    _backfill_sqlite_raw_file_parse_signatures(engine)
    _backfill_sqlite_library_chat_sessions(engine)
    _apply_sqlite_additive_index_updates(engine)
    drift = _inspect_sqlite_schema_drift(engine)
    if drift is None:
        return engine

    if not is_local_mode():
        raise RuntimeError(
            "Database schema drift detected for non-local mode. "
            f"db_path={db_path}, unexpected_tables={drift['unexpected_tables']}, "
            f"missing_columns={drift['missing_columns']}, "
            f"unexpected_columns={drift['unexpected_columns']}"
        )

    logger.warning(
        "local_sqlite_schema_drift_detected",
        db_path=str(db_path),
        unexpected_tables=drift["unexpected_tables"],
        missing_columns=drift["missing_columns"],
        unexpected_columns=drift["unexpected_columns"],
    )
    reset_runtime_state()
    backup_dir = _backup_sqlite_files_before_rebuild(db_path)
    _remove_sqlite_files(db_path)
    rebuilt_engine = get_engine()
    logger.warning(
        "local_sqlite_database_rebuilt",
        db_path=str(db_path),
        backup_dir=str(backup_dir) if backup_dir else "",
    )
    return rebuilt_engine


def _build_sqlite_engine() -> sa.Engine:
    """创建 SQLite 引擎（本地模式）。"""

    db_path = _get_db_path()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        json_serializer=_json_dumps,
        json_deserializer=_json_loads,
    )

    @sa.event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_conn, connection_record):
        del connection_record
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    logger.info("database_engine_created", dialect="sqlite", db_path=str(db_path))
    return engine


def _bounded_env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, get_env_int(name, default)))


def _postgres_pool_config() -> dict[str, int | bool]:
    """Return PostgreSQL pool settings constrained to sane deployment bounds."""

    pool_recycle = get_env_int("DB_POOL_RECYCLE", 1800)
    return {
        "pool_size": _bounded_env_int("DB_POOL_SIZE", 5, min_value=1, max_value=50),
        "max_overflow": _bounded_env_int("DB_MAX_OVERFLOW", 5, min_value=0, max_value=100),
        "pool_timeout": _bounded_env_int("DB_POOL_TIMEOUT", 30, min_value=1, max_value=120),
        "pool_recycle": -1 if pool_recycle < 0 else max(30, min(86400, pool_recycle)),
        "pool_use_lifo": get_env_bool("DB_POOL_USE_LIFO", True),
    }


def _build_postgres_engine(settings) -> sa.Engine:
    """创建 PostgreSQL 引擎（云端模式）。"""

    database_url = (get_env("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError(
            "APP_MODE=cloud requires DATABASE_URL to be set. "
            "Example: postgresql+psycopg://user:pass@host:5432/dbname"
        )

    pool_config = _postgres_pool_config()
    engine = create_engine(
        database_url,
        **pool_config,
        pool_pre_ping=True,
        json_serializer=_json_dumps,
        json_deserializer=_json_loads,
    )
    logger.info("database_engine_created", dialect="postgresql", **pool_config)
    return engine


def get_engine() -> sa.Engine:
    """Create or return the shared SQLAlchemy engine."""

    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    if is_cloud_mode():
        _engine = _build_postgres_engine(settings)
    else:
        _engine = _build_sqlite_engine()

    return _engine


def is_sqlite() -> bool:
    """当前引擎是否为 SQLite。"""

    return get_engine().dialect.name == "sqlite"


def is_postgres() -> bool:
    """当前引擎是否为 PostgreSQL。"""

    return get_engine().dialect.name == "postgresql"


def quote_sqlite_identifier(identifier: str) -> str:
    """Quote one SQLite identifier safely."""

    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _normalize_postgres_vector_target(table_name: str) -> str:
    resolved_llamaindex_table = extract_postgres_course_index_data_table_name(table_name)
    if resolved_llamaindex_table:
        return resolved_llamaindex_table
    return table_name


def _postgres_table_exists(connection: sa.Connection, table_name: str) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _postgres_vector_dim(connection: sa.Connection, *, table_name: str, column_name: str) -> int | None:
    row = connection.execute(
        sa.text(
            """
            SELECT pg_catalog.format_type(a.atttypid, a.atttypmod) AS formatted_type
            FROM pg_catalog.pg_attribute AS a
            JOIN pg_catalog.pg_class AS c
              ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace AS n
              ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = :table_name
              AND a.attname = :column_name
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    if row is None or row[0] is None:
        return None

    match = re.search(r"vector\((\d+)\)", str(row[0]))
    if match is None:
        return None
    return int(match.group(1))
def _postgres_extension_exists(connection: sa.Connection, extension_name: str) -> bool:
    row = connection.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = :extension_name"),
        {"extension_name": extension_name},
    ).first()
    return row is not None


def _get_alembic_head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(get_backend_root() / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if not head:
        raise RuntimeError("Alembic has no head revision.")
    return str(head)


def _get_postgres_alembic_revision(connection: sa.Connection) -> str | None:
    if not _postgres_table_exists(connection, "alembic_version"):
        return None
    rows = list(connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars())
    if len(rows) != 1:
        return ",".join(str(row) for row in rows) if rows else None
    return str(rows[0])


def _collect_postgres_runtime_schema_errors(
    connection: sa.Connection,
    settings,
) -> list[str]:
    errors: list[str] = []

    try:
        expected_revision = _get_alembic_head_revision()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cannot load Alembic head revision: {exc}")
        expected_revision = None

    current_revision = _get_postgres_alembic_revision(connection)
    if expected_revision and current_revision != expected_revision:
        errors.append(
            "alembic revision mismatch: "
            f"current={current_revision or 'missing'}, expected={expected_revision}"
        )

    if not _postgres_extension_exists(connection, "vector"):
        errors.append("missing PostgreSQL extension: vector")

    missing_tables = [
        table.name
        for table in _SCHEMA_TABLES
        if not _postgres_table_exists(connection, table.name)
    ]
    if missing_tables:
        errors.append(f"missing tables: {', '.join(missing_tables)}")

    return errors


def validate_postgres_runtime_schema(
    engine: sa.Engine | None = None,
    settings=None,
) -> list[str]:
    """Return cloud PostgreSQL schema readiness errors."""

    resolved_engine = engine or get_engine()
    resolved_settings = settings or get_settings()
    with resolved_engine.connect() as connection:
        return _collect_postgres_runtime_schema_errors(connection, resolved_settings)


def assert_postgres_runtime_schema_ready(
    engine: sa.Engine | None = None,
    settings=None,
) -> None:
    errors = validate_postgres_runtime_schema(engine=engine, settings=settings)
    if errors:
        detail = "\n".join(f"- {error}" for error in errors)
        raise RuntimeError(
            "PostgreSQL schema is not ready. Run "
            "`python scripts/bootstrap_cloud_db.py` "
            "(or `alembic upgrade head && python scripts/prepare_cloud_db.py && "
            "python scripts/check_cloud_db.py`) before starting the app. "
            "If Render free does not support Pre-Deploy, use "
            "`python scripts/start_cloud_app.py --host 0.0.0.0 --port $PORT` as the Start Command.\n"
            f"{detail}"
        )


def prepare_postgres_runtime_schema(
    *,
    prepare_llamaindex: bool = True,
) -> None:
    """Prepare cloud-only runtime database objects that are outside metadata."""

    if not is_cloud_mode():
        raise RuntimeError("prepare_postgres_runtime_schema requires APP_MODE=cloud.")

    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        current_revision = _get_postgres_alembic_revision(connection)
        expected_revision = _get_alembic_head_revision()
        if current_revision != expected_revision:
            raise RuntimeError(
                "Alembic revision mismatch before runtime schema preparation. "
                f"current={current_revision or 'missing'}, expected={expected_revision}. "
                "Run `alembic upgrade head` first."
            )
        if not _postgres_table_exists(connection, "retrieval_chunk"):
            raise RuntimeError("Missing table retrieval_chunk. Run `alembic upgrade head` first.")

    if prepare_llamaindex:
        from app.shared.infra.search.llamaindex_index.manager import prepare_postgres_store

        prepare_postgres_store()

    logger.info(
        "postgres_runtime_schema_prepared",
        prepare_llamaindex=prepare_llamaindex,
    )


def reset_postgres_public_schema() -> None:
    """Drop and recreate the public schema for one cloud PostgreSQL database.

    This is an explicit operator action intended only for one-time cleanup of a
    legacy or disposable cloud database before rerunning Alembic migrations.
    It is intentionally *not* called from app startup.
    """

    if not is_cloud_mode():
        raise RuntimeError("reset_postgres_public_schema requires APP_MODE=cloud.")

    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))
        connection.execute(sa.text("GRANT ALL ON SCHEMA public TO CURRENT_USER"))
        connection.execute(sa.text("GRANT ALL ON SCHEMA public TO PUBLIC"))

    logger.warning("postgres_public_schema_reset_completed")


def _drop_postgres_removed_schema(connection: sa.Connection) -> None:
    for table_name, column_names in _REMOVED_POSTGRES_COLUMNS.items():
        if not _postgres_table_exists(connection, table_name):
            continue
        for column_name in column_names:
            connection.execute(
                sa.text(
                    f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {column_name}"
                )
            )

    for table_name in _REMOVED_POSTGRES_TABLES:
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))


def vector_table_exists(connection: sa.Connection, table_name: str) -> bool:
    """Check whether one vector table exists."""

    if connection.dialect.name == "postgresql":
        normalized = _normalize_postgres_vector_target(table_name)
        return _postgres_table_exists(connection, normalized)

    row = connection.execute(
        sa.text("SELECT name FROM sqlite_master WHERE name = :table_name"),
        {"table_name": table_name},
    ).first()
    return row is not None


def get_vector_table_dim(connection: sa.Connection, table_name: str) -> int | None:
    """Parse the configured vector dimension for one table."""

    if connection.dialect.name == "postgresql":
        normalized = _normalize_postgres_vector_target(table_name)
        return _postgres_vector_dim(
            connection,
            table_name=normalized,
            column_name="embedding",
        )

    row = connection.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE name = :table_name"),
        {"table_name": table_name},
    ).first()
    if row is None or row[0] is None:
        return None

    match = re.search(r"FLOAT\[(\d+)\]", str(row[0]))
    if match is None:
        return None
    return int(match.group(1))


def _ensure_default_local_user(engine) -> None:
    with Session(engine, expire_on_commit=False) as session:
        user = session.get(User, "local")
        if user is None:
            session.add(
                User(
                    id="local",
                    username="local",
                    email=None,
                    last_seen_ip=None,
                    profile_json="{}",
                )
            )
            session.commit()


def _ensure_builtin_question_types(engine: sa.Engine) -> None:
    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as session:
        for payload in BUILTIN_QUESTION_TYPE_ROWS:
            existing = session.exec(
                select(QuestionTypeRegistry).where(
                    QuestionTypeRegistry.scope == "global",
                    QuestionTypeRegistry.course_id == "",
                    QuestionTypeRegistry.type_key == payload["type_key"],
                )
            ).first()
            if existing is None:
                existing = QuestionTypeRegistry(
                    scope="global",
                    course_id="",
                    source="system",
                    is_system=True,
                    is_active=True,
                    confidence=1.0,
                    created_at=now,
                )
            for key, value in payload.items():
                setattr(existing, key, value)
            existing.updated_at = now
            session.add(existing)
        session.commit()


def _settings_snapshot_payload(settings) -> dict[str, object]:
    return settings.model_dump(mode="json")


def _settings_snapshot_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _upsert_settings_snapshot(
    engine: sa.Engine,
    settings,
    *,
    clear_runtime_overrides: bool = False,
) -> None:
    payload = _settings_snapshot_payload(settings)
    now = datetime.now(timezone.utc)
    settings_hash = _settings_snapshot_hash(payload)
    settings_source = describe_project_settings_source()

    with Session(engine, expire_on_commit=False) as session:
        row = session.get(SystemRuntimeSettings, "runtime")
        if row is None:
            row = SystemRuntimeSettings(id="runtime", settings_json={}, created_at=now)
        if clear_runtime_overrides:
            row.settings_json = {}
        row.settings_source = settings_source
        row.settings_hash = settings_hash
        row.effective_settings_json = payload
        row.updated_at = now
        session.add(row)
        session.commit()


def _load_local_runtime_settings_override(engine: sa.Engine) -> None:
    with Session(engine, expire_on_commit=False) as session:
        row = session.get(SystemRuntimeSettings, "runtime")
        payload = row.settings_json if row is not None and isinstance(row.settings_json, dict) else {}
    settings_payload, env_overrides = split_runtime_settings_payload(payload)
    set_runtime_env_overrides(env_overrides)
    set_system_settings_override(settings_payload)


def init_db() -> None:
    """Initialize the database schema and runtime helpers."""

    if is_cloud_mode():
        set_runtime_env_overrides({})
        clear_system_settings_override()
        _init_postgres_db(get_settings())
    else:
        _init_local_sqlite_db()


def _init_local_sqlite_db() -> None:
    """Initialize the local SQLite schema and runtime settings."""

    engine = _ensure_local_sqlite_schema(get_engine())

    SQLModel.metadata.create_all(engine, tables=_SCHEMA_TABLES)
    _load_local_runtime_settings_override(engine)
    _ensure_default_local_user(engine)
    _ensure_builtin_question_types(engine)
    settings = get_settings()
    _upsert_settings_snapshot(engine, settings)

    logger.info(
        "database_initialized",
        mode="local",
        embedding_model=settings.normalized_embedding_model,
        embedding_dim=settings.embedding_dim,
        table_count=len(_SCHEMA_TABLES),
    )


def _init_postgres_db(settings) -> None:
    """PostgreSQL startup guard.

    Cloud DDL is owned by Alembic and the Render pre-deploy preparation step.
    App startup intentionally validates only, so a bad migration fails before
    the new Render instance receives traffic.
    """

    engine = get_engine()
    assert_postgres_runtime_schema_ready(engine=engine, settings=settings)
    _upsert_settings_snapshot(engine, settings, clear_runtime_overrides=True)

    dim = settings.embedding_dim
    logger.info(
        "database_initialized",
        mode="cloud",
        embedding_model=settings.normalized_embedding_model,
        embedding_dim=dim,
        table_count=len(_SCHEMA_TABLES),
    )


def get_session() -> Session:
    """Return a database session."""

    return Session(get_engine(), expire_on_commit=False)


@contextmanager
def managed_session() -> Generator[Session, None, None]:
    """Provide a managed session with automatic commit/rollback."""

    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
