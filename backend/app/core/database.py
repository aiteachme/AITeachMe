"""Database bootstrap for the new runtime schema."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import sqlalchemy as sa
import structlog
from sqlmodel import SQLModel, Session, create_engine, select

from app.core.config import get_settings
from app.core.exceptions import VectorExtensionUnavailableError

logger = structlog.get_logger()


def _bootstrap_sqlite_driver() -> str:
    try:
        import pysqlite3 as sqlite3  # type: ignore[import-not-found]

        sys.modules["sqlite3"] = sqlite3
        return "pysqlite3-binary"
    except ImportError:
        import sqlite3 as sqlite3  # noqa: F401

        return "stdlib-sqlite3"


def _bootstrap_sqlite_vec():
    try:
        import sqlite_vec as sqlite_vec_module
    except ImportError:
        return None
    return sqlite_vec_module


_SQLITE_DRIVER = _bootstrap_sqlite_driver()
sqlite_vec = _bootstrap_sqlite_vec()

_engine = None
_vec_ready: bool | None = None
_vec_error: str | None = None

_SCHEMA_SENTINELS: dict[str, set[str]] = {
    "user": {"id", "username", "profile_json"},
    "subject": {"id", "user_id", "slug", "name"},
    "raw_file": {
        "id",
        "user_id",
        "subject_id",
        "uid",
        "original_filename",
        "storage_key",
        "parsed_markdown",
        "parser_used",
        "parse_metadata_json",
        "classification_json",
        "digest_current_step",
    },
    "raw_file_asset": {"id", "raw_file_id", "asset_name", "storage_key"},
    "retrieval_chunk": {
        "id",
        "user_id",
        "subject_id",
        "source_type",
        "source_id",
        "chunk_role",
        "chunk_index",
        "digest_chunk_uid",
        "content",
    },
    "knowledge_document": {"id", "user_id", "subject_id", "content_markdown", "version_no"},
    "knowledge_node": {"id", "user_id", "subject_id", "summary", "body"},
    "curriculum_version": {"id", "user_id", "subject_id", "version_no", "metadata_json"},
    "exam_paper": {"id", "user_id", "subject_id", "metadata_json", "status"},
}


def _set_vec_status(ready: bool, error: str | None = None) -> None:
    global _vec_ready, _vec_error
    _vec_ready = ready
    _vec_error = error


def is_vec_ready() -> bool:
    return bool(_vec_ready)


def require_vec_ready() -> None:
    if not is_vec_ready():
        raise VectorExtensionUnavailableError(_vec_error or "")


def get_vec_status() -> tuple[bool | None, str | None]:
    return _vec_ready, _vec_error


def reset_runtime_state() -> None:
    global _engine, _vec_ready, _vec_error
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _vec_ready = None
    _vec_error = None


def _load_vec_extension(dbapi_conn) -> None:
    if sqlite_vec is None:
        _set_vec_status(False, "sqlite-vec not installed")
        logger.warning("sqlite_vec_unavailable", reason="sqlite-vec not installed")
        return

    can_toggle_extensions = hasattr(dbapi_conn, "enable_load_extension")
    try:
        if can_toggle_extensions:
            dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        _set_vec_status(True, None)
        logger.info(
            "sqlite_vec_loaded",
            sqlite_driver=_SQLITE_DRIVER,
            supports_enable_load_extension=can_toggle_extensions,
        )
    except Exception as exc:  # noqa: BLE001
        _set_vec_status(False, str(exc))
        logger.warning(
            "sqlite_vec_unavailable",
            sqlite_driver=_SQLITE_DRIVER,
            supports_enable_load_extension=can_toggle_extensions,
            error=str(exc),
        )
    finally:
        if can_toggle_extensions:
            try:
                dbapi_conn.enable_load_extension(False)
            except Exception:  # noqa: BLE001
                logger.warning("sqlite_extension_disable_failed")


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    db_dir = Path(settings.data_dir).resolve()
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "aiteachme.db"

    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @sa.event.listens_for(_engine, "connect")
    def load_vec_extension(dbapi_conn, connection_record):
        del connection_record
        _load_vec_extension(dbapi_conn)

    logger.info("database_engine_created", db_path=str(db_path), sqlite_driver=_SQLITE_DRIVER)
    return _engine


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name = :table_name"),
        {"table_name": table_name},
    ).first()
    return row is not None


def _get_table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(sa.text(f"PRAGMA table_info('{table_name}')")).fetchall()
    return {str(row[1]) for row in rows}


def _delete_db_file(db_path: Path) -> None:
    for sidecar_suffix in ("", "-wal", "-shm", "-journal"):
        target = Path(f"{db_path}{sidecar_suffix}") if sidecar_suffix else db_path
        target.unlink(missing_ok=True)


def _schema_needs_rebuild(engine) -> tuple[bool, str | None]:
    with engine.connect() as conn:
        for table_name, expected_columns in _SCHEMA_SENTINELS.items():
            if not _table_exists(conn, table_name):
                if table_name == "user":
                    return True, f"missing table: {table_name}"
                continue
            existing_columns = _get_table_columns(conn, table_name)
            missing_columns = sorted(expected_columns - existing_columns)
            if missing_columns:
                return True, f"{table_name} missing columns: {', '.join(missing_columns)}"
    return False, None


def _create_embedding_table(engine, *, embedding_dim: int) -> None:
    if not is_vec_ready():
        logger.warning(
            "database_initialized_without_vec",
            embedding_dim=embedding_dim,
            sqlite_driver=_SQLITE_DRIVER,
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
    from app.models import User

    with Session(engine, expire_on_commit=False) as session:
        local_user = session.exec(select(User).where(User.username == "local")).first()
        if local_user is not None:
            return
        session.add(User(username="local", profile_json="{}"))
        session.commit()
        logger.info("database_local_user_bootstrapped")


def _init_db_once(engine) -> None:
    settings = get_settings()
    SQLModel.metadata.create_all(engine)
    _create_embedding_table(engine, embedding_dim=settings.embedding_dim)
    _ensure_default_local_user(engine)
    logger.info(
        "database_initialized",
        embedding_dim=settings.embedding_dim,
        sqlite_driver=_SQLITE_DRIVER,
        vec_ready=is_vec_ready(),
    )


def init_db() -> None:
    """Initialize the new runtime database schema."""

    from app import models as _  # noqa: F401

    settings = get_settings()
    db_path = Path(settings.data_dir).resolve() / "aiteachme.db"
    engine = get_engine()

    should_rebuild, reason = _schema_needs_rebuild(engine)
    if should_rebuild and db_path.exists():
        logger.warning("database_schema_rebuild_required", db_path=str(db_path), reason=reason)
        reset_runtime_state()
        _delete_db_file(db_path)
        engine = get_engine()

    _init_db_once(engine)


def get_session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


@contextmanager
def managed_session() -> Generator[Session, None, None]:
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
