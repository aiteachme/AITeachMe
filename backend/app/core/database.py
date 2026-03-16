"""数据库初始化、轻量迁移与会话管理。"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import pysqlite3 as sqlite3  # type: ignore[import-not-found]

    sys.modules["sqlite3"] = sqlite3
    _SQLITE_DRIVER = "pysqlite3-binary"
except ImportError:
    import sqlite3  # noqa: F401

    _SQLITE_DRIVER = "stdlib-sqlite3"

import sqlalchemy as sa
import sqlite_vec
import structlog
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import get_settings
from app.core.exceptions import VectorExtensionUnavailableError

logger = structlog.get_logger()

_engine = None
_vec_ready: bool | None = None
_vec_error: str | None = None


def _set_vec_status(ready: bool, error: str | None = None) -> None:
    global _vec_ready, _vec_error
    _vec_ready = ready
    _vec_error = error


def is_vec_ready() -> bool:
    """返回向量扩展是否可用。"""

    return bool(_vec_ready)


def require_vec_ready() -> None:
    """要求 sqlite-vec 已可用。"""

    if not is_vec_ready():
        raise VectorExtensionUnavailableError(_vec_error or "")


def get_vec_status() -> tuple[bool | None, str | None]:
    """返回向量扩展状态与错误信息。"""

    return _vec_ready, _vec_error


def reset_runtime_state() -> None:
    """重置全局单例，便于本地冒烟测试。"""

    global _engine, _vec_ready, _vec_error
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _vec_ready = None
    _vec_error = None


def _load_vec_extension(dbapi_conn) -> None:
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
    except Exception as exc:
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
            except Exception as exc:
                logger.warning("sqlite_extension_disable_failed", error=str(exc))


def get_engine():
    """创建或返回数据库引擎。"""

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

    logger.info("database_engine_created", db_path=str(db_path), sqlite_driver=_SQLITE_DRIVER)
    return _engine


def _get_table_columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(sa.text(f"PRAGMA table_info('{table_name}')")).fetchall()
    return {row[1] for row in rows}


def _ensure_column(conn, table_name: str, column_name: str, ddl: str) -> None:
    if column_name in _get_table_columns(conn, table_name):
        return
    conn.execute(sa.text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = :table_name"
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _apply_lightweight_migrations(engine) -> None:
    """为旧数据库补齐新字段，并把旧状态同步到新字段。"""

    with engine.connect() as conn:
        if _table_exists(conn, "raw_file"):
            raw_file_columns = _get_table_columns(conn, "raw_file")
            _ensure_column(conn, "raw_file", "status", "status TEXT DEFAULT 'pending'")
            _ensure_column(conn, "raw_file", "error_message", "error_message TEXT")
            _ensure_column(conn, "raw_file", "updated_at", "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            if "parse_status" in raw_file_columns:
                conn.execute(
                    sa.text(
                        """
                        UPDATE raw_file
                        SET
                            status = COALESCE(
                                status,
                                CASE parse_status
                                    WHEN 'parsing' THEN 'processing'
                                    WHEN 'parsed' THEN 'completed'
                                    WHEN 'parse_failed' THEN 'failed'
                                    ELSE 'pending'
                                END
                            )
                        """
                    )
                )
            if "parse_error" in raw_file_columns:
                conn.execute(
                    sa.text(
                        """
                        UPDATE raw_file
                        SET error_message = COALESCE(error_message, parse_error)
                        """
                    )
                )

        if _table_exists(conn, "doc_build_job"):
            doc_build_job_columns = _get_table_columns(conn, "doc_build_job")
            _ensure_column(conn, "doc_build_job", "status", "status TEXT DEFAULT 'pending'")
            _ensure_column(conn, "doc_build_job", "current_step", "current_step TEXT")
            _ensure_column(conn, "doc_build_job", "error_message", "error_message TEXT")
            _ensure_column(conn, "doc_build_job", "updated_at", "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            if "stage" in doc_build_job_columns:
                conn.execute(
                    sa.text(
                        """
                        UPDATE doc_build_job
                        SET
                            status = COALESCE(
                                status,
                                CASE stage
                                    WHEN 'failed' THEN 'failed'
                                    WHEN 'embedded' THEN 'completed'
                                    WHEN 'pending' THEN 'pending'
                                    ELSE 'processing'
                                END
                            ),
                            current_step = COALESCE(
                                current_step,
                                CASE stage
                                    WHEN 'cleaned' THEN 'cleaned'
                                    WHEN 'outlined' THEN 'outlined'
                                    WHEN 'stored' THEN 'stored'
                                    WHEN 'chunked' THEN 'chunked'
                                    WHEN 'embedded' THEN 'embedded'
                                    ELSE current_step
                                END
                            )
                        """
                    )
                )
            if "error" in doc_build_job_columns:
                conn.execute(
                    sa.text(
                        """
                        UPDATE doc_build_job
                        SET error_message = COALESCE(error_message, error)
                        """
                    )
                )

        if _table_exists(conn, "document"):
            document_columns = _get_table_columns(conn, "document")
            _ensure_column(conn, "document", "current_step", "current_step TEXT")
            _ensure_column(conn, "document", "updated_at", "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            if "pipeline_stage" in document_columns:
                conn.execute(
                    sa.text(
                        """
                        UPDATE document
                        SET current_step = COALESCE(
                            current_step,
                            CASE pipeline_stage
                                WHEN 'cleaned' THEN 'cleaned'
                                WHEN 'outlined' THEN 'outlined'
                                WHEN 'stored' THEN 'stored'
                                WHEN 'chunked' THEN 'chunked'
                                WHEN 'embedded' THEN 'embedded'
                                ELSE current_step
                            END
                        )
                        """
                    )
                )

        conn.commit()


def init_db() -> None:
    """初始化数据库与向量表。"""

    from app import models as _  # noqa: F401

    engine = get_engine()
    settings = get_settings()

    SQLModel.metadata.create_all(engine)
    _apply_lightweight_migrations(engine)

    if is_vec_ready():
        with engine.connect() as conn:
            conn.execute(
                sa.text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
                    f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{settings.embedding_dim}])"
                )
            )
            conn.commit()
    else:
        logger.warning(
            "database_initialized_without_vec",
            embedding_dim=settings.embedding_dim,
            sqlite_driver=_SQLITE_DRIVER,
            vec_error=_vec_error,
        )

    logger.info(
        "database_initialized",
        embedding_dim=settings.embedding_dim,
        sqlite_driver=_SQLITE_DRIVER,
        vec_ready=is_vec_ready(),
    )


def get_session() -> Session:
    """返回一个新的数据库会话。"""

    return Session(get_engine())
