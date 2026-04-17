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
from sqlmodel import Session, SQLModel, create_engine

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env, resolve_project_settings_path
from app.shared.infra.exceptions import VectorExtensionUnavailableError
from app.shared.infra.runtime import is_cloud_mode, is_local_mode
from app.shared.infra.runtime import get_sqlite_db_path
from app.shared.infra.subject import (
    build_subject_vector_table_name,
    get_postgres_vector_ref,
)
from app.models.build_planner import BuildPlannerSession, BuildPlannerTurn, ConfirmedBuildPlan
from app.models.chat import ChatMessage, ChatSession
from app.models.email_verification import EmailVerificationCode
from app.models.exam import ExamPaper, ExamPaperItem, QuestionTemplate
from app.models.knowledge import RetrievalChunk
from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.curriculum import Curriculum, TaxonomyAnchor, TeachingUnit, ThemeTreeNode, UnitDependency
from app.models.profile import UserKnowledgeState
from app.models.raw_file import RawFile
from app.models.subject import Subject
from app.models.system import SystemSettingsSnapshot
from app.models.user import User

logger = structlog.get_logger()

try:
    import sqlite_vec
except ImportError as exc:
    sqlite_vec = None
    _SQLITE_VEC_IMPORT_ERROR = str(exc)
else:
    _SQLITE_VEC_IMPORT_ERROR = None

_engine = None
_vec_ready: bool | None = None
_vec_error: str | None = None
_SCHEMA_MODELS = (
    User,
    EmailVerificationCode,
    Subject,
    RawFile,
    BuildPlannerSession,
    BuildPlannerTurn,
    ConfirmedBuildPlan,
    RetrievalChunk,
    KnowledgeDocument,
    KnowledgeUnit,
    KnowledgeEdge,
    Curriculum,
    TeachingUnit,
    ThemeTreeNode,
    TaxonomyAnchor,
    UnitDependency,
    QuestionTemplate,
    ExamPaper,
    ExamPaperItem,
    UserKnowledgeState,
    ChatSession,
    ChatMessage,
    SystemSettingsSnapshot,
)
_SCHEMA_TABLES = [model.__table__ for model in _SCHEMA_MODELS]
_EXPECTED_SCHEMA_COLUMNS = {
    table.name: {column.name for column in table.columns}
    for table in _SCHEMA_TABLES
}
_ALLOWED_SQLITE_RUNTIME_TABLES = {"sqlite_sequence"}
_ALLOWED_SQLITE_RUNTIME_PREFIXES = ("chunk_embeddings_",)


def _set_vec_status(ready: bool, error: str | None = None) -> None:
    global _vec_ready, _vec_error
    _vec_ready = ready
    _vec_error = error


def is_vec_ready() -> bool:
    """Return whether vector extension is available for the current runtime."""

    if is_postgres():
        return True  # pgvector 在 init_db 时已确认
    return bool(_vec_ready)


def require_vec_ready() -> None:
    """Raise when vector features are unavailable."""

    if not is_vec_ready():
        raise VectorExtensionUnavailableError(_vec_error or "")


def get_vec_status() -> tuple[bool | None, str | None]:
    """Return sqlite-vec availability and the last error message."""

    return _vec_ready, _vec_error


def reset_runtime_state() -> None:
    """Reset cached engine/runtime flags for local restart scenarios."""

    global _engine, _vec_ready, _vec_error
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _vec_ready = None
    _vec_error = None


def _load_vec_extension(dbapi_conn) -> None:
    if sqlite_vec is None:
        _set_vec_status(False, _SQLITE_VEC_IMPORT_ERROR)
        logger.warning("sqlite_vec_unavailable", error=_SQLITE_VEC_IMPORT_ERROR)
        return

    can_toggle_extensions = hasattr(dbapi_conn, "enable_load_extension")
    try:
        if can_toggle_extensions:
            dbapi_conn.enable_load_extension(True)

        sqlite_vec.load(dbapi_conn)
        _set_vec_status(True, None)
        logger.info(
            "sqlite_vec_loaded",
            supports_enable_load_extension=can_toggle_extensions,
        )
    except Exception as exc:
        _set_vec_status(False, str(exc))
        logger.warning(
            "sqlite_vec_unavailable",
            supports_enable_load_extension=can_toggle_extensions,
            error=str(exc),
        )
    finally:
        if can_toggle_extensions:
            try:
                dbapi_conn.enable_load_extension(False)
            except Exception as exc:
                logger.warning("sqlite_extension_disable_failed", error=str(exc))


def _get_db_path():
    return get_sqlite_db_path()


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


def _ensure_local_sqlite_schema(engine: sa.Engine) -> sa.Engine:
    db_path = _get_db_path()
    if not db_path.exists():
        return engine

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
        _load_vec_extension(dbapi_conn)

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
    if table_name == get_postgres_vector_ref():
        return table_name
    if table_name.startswith("chunk_embeddings_"):
        return get_postgres_vector_ref()
    return table_name


def _postgres_column_exists(
    connection: sa.Connection,
    *,
    table_name: str,
    column_name: str,
) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


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


def _postgres_vector_dim(
    connection: sa.Connection,
    *,
    table_name: str,
    column_name: str,
) -> int | None:
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


def _ensure_postgres_embedding_column(
    connection: sa.Connection,
    *,
    embedding_dim: int,
    reset: bool = False,
) -> None:
    current_dim = _postgres_vector_dim(
        connection,
        table_name="retrieval_chunk",
        column_name="embedding",
    )

    if current_dim is None:
        connection.execute(
            sa.text(
                f"ALTER TABLE retrieval_chunk "
                f"ADD COLUMN IF NOT EXISTS embedding vector({embedding_dim})"
            )
        )
    elif current_dim != embedding_dim:
        connection.execute(sa.text("DROP INDEX IF EXISTS idx_retrieval_chunk_embedding"))
        connection.execute(sa.text("ALTER TABLE retrieval_chunk DROP COLUMN IF EXISTS embedding"))
        connection.execute(
            sa.text(
                f"ALTER TABLE retrieval_chunk "
                f"ADD COLUMN embedding vector({embedding_dim})"
            )
        )
    elif reset:
        logger.info(
            "postgres_embedding_column_reset_skipped",
            reason="dimension_unchanged",
            embedding_dim=embedding_dim,
        )

    connection.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_retrieval_chunk_embedding "
            "ON retrieval_chunk "
            "USING hnsw (embedding vector_cosine_ops)"
        )
    )


def vector_table_exists(connection: sa.Connection, table_name: str) -> bool:
    """Check whether one vector table exists."""

    if connection.dialect.name == "postgresql":
        normalized = _normalize_postgres_vector_target(table_name)
        if normalized == get_postgres_vector_ref():
            return _postgres_table_exists(connection, "retrieval_chunk") and _postgres_column_exists(
                connection,
                table_name="retrieval_chunk",
                column_name="embedding",
            )
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
        if normalized == get_postgres_vector_ref():
            return _postgres_vector_dim(
                connection,
                table_name="retrieval_chunk",
                column_name="embedding",
            )
        return None

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


def ensure_subject_vec_table(engine: sa.Engine, *, subject: str, embedding_dim: int) -> str:
    """Ensure one subject-scoped sqlite-vec table exists with the requested dimension."""

    table_name = (
        get_postgres_vector_ref()
        if engine.dialect.name == "postgresql"
        else build_subject_vector_table_name(subject)
    )
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            _ensure_postgres_embedding_column(connection, embedding_dim=embedding_dim)
        return table_name

    if not is_vec_ready():
        logger.warning(
            "database_vec_table_unavailable",
            subject=subject,
            table_name=table_name,
            embedding_dim=embedding_dim,
            vec_error=_vec_error,
        )
        return table_name

    quoted_table_name = quote_sqlite_identifier(table_name)
    with engine.begin() as connection:
        existing_dim = get_vector_table_dim(connection, table_name)
        if existing_dim is not None and existing_dim != embedding_dim:
            connection.execute(sa.text(f"DROP TABLE IF EXISTS {quoted_table_name}"))
        connection.execute(
            sa.text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {quoted_table_name} "
                f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{embedding_dim}])"
            )
        )
    return table_name


def reset_subject_vec_table(engine: sa.Engine, *, subject: str, embedding_dim: int) -> str:
    """Drop and recreate the subject-scoped vector table."""

    table_name = (
        get_postgres_vector_ref()
        if engine.dialect.name == "postgresql"
        else build_subject_vector_table_name(subject)
    )
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            _ensure_postgres_embedding_column(
                connection,
                embedding_dim=embedding_dim,
                reset=True,
            )
        return table_name

    if not is_vec_ready():
        logger.warning(
            "database_vec_table_reset_skipped",
            subject=subject,
            table_name=table_name,
            embedding_dim=embedding_dim,
            vec_error=_vec_error,
        )
        return table_name

    quoted_table_name = quote_sqlite_identifier(table_name)
    with engine.begin() as connection:
        connection.execute(sa.text(f"DROP TABLE IF EXISTS {quoted_table_name}"))
        connection.execute(
            sa.text(
                f"CREATE VIRTUAL TABLE {quoted_table_name} "
                f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{embedding_dim}])"
            )
        )
    return table_name


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


def _settings_snapshot_payload(settings) -> dict[str, object]:
    return settings.model_dump(mode="json")


def _settings_snapshot_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _upsert_settings_snapshot(engine: sa.Engine, settings) -> None:
    payload = _settings_snapshot_payload(settings)
    now = datetime.now(timezone.utc)
    settings_hash = _settings_snapshot_hash(payload)
    settings_path = str(resolve_project_settings_path())

    with Session(engine, expire_on_commit=False) as session:
        snapshot = session.get(SystemSettingsSnapshot, "runtime")
        if snapshot is None:
            snapshot = SystemSettingsSnapshot(id="runtime", created_at=now)
        snapshot.settings_path = settings_path
        snapshot.settings_hash = settings_hash
        snapshot.settings_json = payload
        snapshot.updated_at = now
        session.add(snapshot)
        session.commit()


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
    _ensure_default_local_user(engine)
    _upsert_settings_snapshot(engine, settings)

    logger.info(
        "database_initialized",
        mode="local",
        embedding_model=settings.normalized_embedding_model,
        embedding_dim=settings.embedding_dim,
        table_count=len(_SCHEMA_TABLES),
        vec_ready=is_vec_ready(),
    )


def _init_postgres_db(settings) -> None:
    """PostgreSQL + pgvector 初始化。"""

    engine = get_engine()

    # 确保 pgvector 扩展可用
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    SQLModel.metadata.create_all(engine, tables=_SCHEMA_TABLES)
    _upsert_settings_snapshot(engine, settings)

    # 为 retrieval_chunk 添加 embedding 向量列（如果不存在）
    dim = settings.embedding_dim
    if dim:
        with engine.begin() as conn:
            _ensure_postgres_embedding_column(conn, embedding_dim=dim)

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
