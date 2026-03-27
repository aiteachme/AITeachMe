"""Database bootstrap and session helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import sqlalchemy as sa
import structlog
from sqlmodel import SQLModel, Session, create_engine

import app.models
from app.core.config import get_settings
from app.core.exceptions import VectorExtensionUnavailableError

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


def get_engine():
    """Create or return the shared SQLAlchemy engine."""

    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    db_dir = Path(settings.data_dir)
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


def init_db() -> None:
    """Initialize the local database schema and vector table."""

    settings = get_settings()
    engine = get_engine()

    SQLModel.metadata.create_all(engine)
    _ensure_vec_table(engine, embedding_dim=settings.embedding_dim)

    logger.info(
        "database_initialized",
        embedding_dim=settings.embedding_dim,
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
