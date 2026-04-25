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
from typing import Generator

import sqlalchemy as sa
import structlog
from sqlmodel import Session, SQLModel, create_engine, select

from app.shared.infra.settings import (
    clear_system_settings_override,
    get_settings,
    reset_project_settings_cache,
    set_system_settings_override,
)
from app.shared.infra.env_support import (
    describe_project_settings_source,
    get_env,
)
from app.shared.infra.runtime import get_backend_root, is_cloud_mode, is_local_mode
from app.shared.infra.runtime import get_sqlite_db_path
from app.shared.infra.subject import (
    extract_postgres_subject_index_data_table_name,
)
from migrations.seed_data.question_types import BUILTIN_QUESTION_TYPE_ROWS
from app.models.build_planner import ConfirmedBuildPlan
from app.models.chat import ChatMessage, ChatSession
from app.models.email_verification import EmailVerificationCode
from app.models.exam import ExamPaper, ExamPaperItem, QuestionTemplate, QuestionTypeRegistry
from app.models.knowledge import RetrievalChunk
from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.profile import UserKnowledgeState
from app.models.raw_file import RawFile, SubjectFileLink
from app.models.subject import Subject
from app.models.system import SystemRuntimeSettings, SystemSettingsSnapshot, UserRuntimeSettings
from app.models.user import User

logger = structlog.get_logger()

_engine = None
_SCHEMA_MODELS = (
    User,
    EmailVerificationCode,
    Subject,
    RawFile,
    SubjectFileLink,
    ConfirmedBuildPlan,
    RetrievalChunk,
    KnowledgeDocument,
    KnowledgeUnit,
    KnowledgeEdge,
    QuestionTypeRegistry,
    QuestionTemplate,
    ExamPaper,
    ExamPaperItem,
    UserKnowledgeState,
    ChatSession,
    ChatMessage,
    SystemRuntimeSettings,
    SystemSettingsSnapshot,
    UserRuntimeSettings,
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
    "unit_dependency",
    "theme_tree_node",
    "taxonomy_anchor",
    "teaching_unit",
    "curriculum",
    "build_planner_turn",
    "build_planner_session",
)
_REMOVED_POSTGRES_COLUMNS = {
    "question_template": ("curriculum_version_id",),
    "exam_paper": ("curriculum_version_id", "theme_tree_node_id"),
}
_REMOVED_SQLITE_TABLES = _REMOVED_POSTGRES_TABLES
_REMOVED_SQLITE_COLUMNS = {
    **_REMOVED_POSTGRES_COLUMNS,
    "chat_session": ("user_goal",),
    "system_settings_snapshot": ("settings_path",),
}


def _get_db_path():
    return get_sqlite_db_path()


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


def _remove_sqlite_files(db_path: Path) -> None:
    for suffix in ("", "-shm", "-wal"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


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


def _drop_sqlite_removed_schema(engine: sa.Engine) -> None:
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


def _drop_sqlite_legacy_schema(engine: sa.Engine) -> None:
    """Backward-compatible alias for older tests and local tooling."""

    _drop_sqlite_removed_schema(engine)


def _add_missing_sqlite_column(
    connection: sa.Connection,
    *,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    connection.execute(
        sa.text(
            f"ALTER TABLE {quote_sqlite_identifier(table_name)} "
            f"ADD COLUMN {quote_sqlite_identifier(column_name)} {column_sql}"
        )
    )


def _apply_sqlite_additive_schema_updates(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "subject" not in existing_tables:
        return

    subject_columns = {
        column["name"]
        for column in inspector.get_columns("subject")
    }
    missing_subject_text_columns = [
        column_name
        for column_name in ("description", "user_intent")
        if column_name not in subject_columns
    ]
    if not missing_subject_text_columns:
        return

    with engine.begin() as connection:
        for column_name in missing_subject_text_columns:
            _add_missing_sqlite_column(
                connection,
                table_name="subject",
                column_name=column_name,
                column_sql="TEXT NOT NULL DEFAULT ''",
            )
            logger.info(
                "sqlite_subject_column_added",
                table_name="subject",
                column_name=column_name,
            )


def _ensure_local_sqlite_schema(engine: sa.Engine) -> sa.Engine:
    db_path = _get_db_path()
    if not db_path.exists():
        return engine

    _drop_sqlite_removed_schema(engine)
    _apply_sqlite_additive_schema_updates(engine)
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
    _remove_sqlite_files(db_path)
    rebuilt_engine = get_engine()
    logger.warning(
        "local_sqlite_database_rebuilt",
        db_path=str(db_path),
    )
    return rebuilt_engine


def _build_sqlite_engine() -> sa.Engine:
    """创建 SQLite 引擎（本地模式）。"""

    db_path = _get_db_path()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @sa.event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_conn, connection_record):
        del connection_record
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    logger.info("database_engine_created", dialect="sqlite", db_path=str(db_path))
    return engine


def _build_postgres_engine(settings) -> sa.Engine:
    """创建 PostgreSQL 引擎（云端模式）。"""

    database_url = (get_env("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError(
            "APP_MODE=cloud requires DATABASE_URL to be set. "
            "Example: postgresql+psycopg://user:pass@host:5432/dbname"
        )

    engine = create_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    logger.info("database_engine_created", dialect="postgresql")
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
    resolved_llamaindex_table = extract_postgres_subject_index_data_table_name(table_name)
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
                    QuestionTypeRegistry.subject == "",
                    QuestionTypeRegistry.type_key == payload["type_key"],
                )
            ).first()
            if existing is None:
                existing = QuestionTypeRegistry(
                    scope="global",
                    subject="",
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


def _upsert_settings_snapshot(engine: sa.Engine, settings) -> None:
    payload = _settings_snapshot_payload(settings)
    now = datetime.now(timezone.utc)
    settings_hash = _settings_snapshot_hash(payload)
    settings_source = describe_project_settings_source()

    with Session(engine, expire_on_commit=False) as session:
        snapshot = session.get(SystemSettingsSnapshot, "runtime")
        if snapshot is None:
            snapshot = SystemSettingsSnapshot(id="runtime", created_at=now)
        snapshot.settings_source = settings_source
        snapshot.settings_hash = settings_hash
        snapshot.settings_json = payload
        snapshot.updated_at = now
        session.add(snapshot)
        session.commit()


def _refresh_system_settings_override(engine: sa.Engine) -> None:
    with Session(engine, expire_on_commit=False) as session:
        row = session.get(SystemRuntimeSettings, "runtime")
        payload = row.settings_json if row is not None and isinstance(row.settings_json, dict) else {}
    set_system_settings_override(payload)


def init_db() -> None:
    """Initialize the database schema and runtime helpers."""

    settings = get_settings()

    if is_cloud_mode():
        _init_postgres_db(settings)
    else:
        _init_local_sqlite_db(settings)


def _init_local_sqlite_db(settings) -> None:
    """本地 SQLite 初始化（原有逻辑）。"""

    engine = _ensure_local_sqlite_schema(get_engine())

    SQLModel.metadata.create_all(engine, tables=_SCHEMA_TABLES)
    _refresh_system_settings_override(engine)
    _ensure_default_local_user(engine)
    _ensure_builtin_question_types(engine)
    _upsert_settings_snapshot(engine, get_settings())

    logger.info(
        "database_initialized",
        mode="local",
        embedding_model=get_settings().normalized_embedding_model,
        embedding_dim=get_settings().embedding_dim,
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
    _refresh_system_settings_override(engine)
    _upsert_settings_snapshot(engine, get_settings())

    dim = get_settings().embedding_dim
    logger.info(
        "database_initialized",
        mode="cloud",
        embedding_model=get_settings().normalized_embedding_model,
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
