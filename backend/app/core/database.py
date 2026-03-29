"""Database bootstrap and session helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import sqlalchemy as sa
import structlog
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings
from app.core.exceptions import VectorExtensionUnavailableError
from app.core.runtime_paths import get_sqlite_db_path, log_legacy_runtime_path_warnings
from app.models.chat import ChatMessage, ChatSession
from app.models.curriculum import (
    Curriculum,
    TaxonomyAnchor,
    TeachingUnit,
    ThemeTreeNode,
    UnitDependency,
)
from app.models.exam import ExamPaper, ExamPaperItem, QuestionTemplate
from app.models.knowledge import RetrievalChunk
from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_graph import KnowledgeEdge, KnowledgeNode
from app.models.profile import UserKnowledgeState
from app.models.raw_file import RawFile
from app.models.subject import Subject
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
    Subject,
    RawFile,
    RetrievalChunk,
    KnowledgeDocument,
    KnowledgeNode,
    KnowledgeEdge,
    TeachingUnit,
    TaxonomyAnchor,
    ThemeTreeNode,
    UnitDependency,
    Curriculum,
    QuestionTemplate,
    ExamPaper,
    ExamPaperItem,
    UserKnowledgeState,
    ChatSession,
    ChatMessage,
)
_SCHEMA_TABLES = [model.__table__ for model in _SCHEMA_MODELS]
_EXPECTED_SCHEMA_COLUMNS = {
    table.name: {column.name for column in table.columns}
    for table in _SCHEMA_TABLES
}
_ALLOWED_SQLITE_RUNTIME_TABLES = {"sqlite_sequence", "chunk_embeddings"}
_ALLOWED_SQLITE_RUNTIME_PREFIXES = ("chunk_embeddings_",)


def _set_vec_status(ready: bool, error: str | None = None) -> None:
    global _vec_ready, _vec_error
    _vec_ready = ready
    _vec_error = error


def is_vec_ready() -> bool:
    """Return whether sqlite-vec is available for the current runtime."""

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
    for table_name, expected_columns in _EXPECTED_SCHEMA_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {
            column["name"]
            for column in inspector.get_columns(table_name)
        }
        missing = sorted(expected_columns - existing_columns)
        if missing:
            missing_columns[table_name] = missing

    if not unexpected_tables and not missing_columns:
        return None

    return {
        "unexpected_tables": unexpected_tables,
        "missing_columns": missing_columns,
    }


def _remove_sqlite_files(db_path: Path) -> None:
    for suffix in ("", "-shm", "-wal"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _ensure_local_sqlite_schema(engine: sa.Engine) -> sa.Engine:
    settings = get_settings()
    db_path = _get_db_path()
    if not db_path.exists():
        return engine

    drift = _inspect_sqlite_schema_drift(engine)
    if drift is None:
        return engine

    if not settings.is_local_mode:
        raise RuntimeError(
            "Database schema drift detected for non-local mode. "
            f"db_path={db_path}, unexpected_tables={drift['unexpected_tables']}, "
            f"missing_columns={drift['missing_columns']}"
        )

    logger.warning(
        "local_sqlite_schema_drift_detected",
        db_path=str(db_path),
        unexpected_tables=drift["unexpected_tables"],
        missing_columns=drift["missing_columns"],
    )
    reset_runtime_state()
    _remove_sqlite_files(db_path)
    rebuilt_engine = get_engine()
    logger.warning(
        "local_sqlite_database_rebuilt",
        db_path=str(db_path),
    )
    return rebuilt_engine


def get_engine() -> sa.Engine:
    """Create or return the shared SQLAlchemy engine."""

    global _engine
    if _engine is not None:
        return _engine

    db_path = _get_db_path()

    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @sa.event.listens_for(_engine, "connect")
    def configure_sqlite(dbapi_conn, connection_record):
        del connection_record
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()
        _load_vec_extension(dbapi_conn)

    logger.info("database_engine_created", db_path=str(db_path))
    return _engine


def _ensure_vec_table(engine, *, embedding_dim: int) -> None:
    if not is_vec_ready():
        logger.warning(
            "database_initialized_without_vec",
            embedding_dim=embedding_dim,
            vec_error=_vec_error,
        )
        return

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
                f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{embedding_dim}])"
            )
        )


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


def init_db() -> None:
    """Initialize the local database schema and vector table."""

    settings = get_settings()
    log_legacy_runtime_path_warnings()
    engine = _ensure_local_sqlite_schema(get_engine())

    SQLModel.metadata.create_all(engine, tables=_SCHEMA_TABLES)
    _ensure_vec_table(engine, embedding_dim=settings.embedding_dim)
    _ensure_default_local_user(engine)

    logger.info(
        "database_initialized",
        embedding_dim=settings.embedding_dim,
        table_count=len(_SCHEMA_TABLES),
        vec_ready=is_vec_ready(),
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
