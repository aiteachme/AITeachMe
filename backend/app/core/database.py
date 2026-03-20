"""数据库初始化、schema 校验与会话管理。"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

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

_SCHEMA_REQUIREMENTS: dict[str, set[str]] = {
    "raw_file": {
        "id",
        "subject",
        "filename",
        "filetype",
        "file_path",
        "markdown_path",
        "asset_dir",
        "status",
        "error_message",
        "created_at",
        "updated_at",
        "content_hash",
        "file_size_bytes",
        "estimated_pages",
        "detected_language",
        "classification_result",
        "quality_score",
        "parse_metadata",
        "image_count",
        "ingest_status",
    },
    "document": {
        "id",
        "subject",
        "source_file_id",
        "title",
        "markdown_content",
        "current_step",
        "created_at",
        "updated_at",
    },
    "graph_digest_job": {
        "id",
        "subject",
        "idempotency_key",
        "status",
        "progress",
        "current_step",
        "input_file_ids_json",
        "input_chunk_count",
        "error_message",
        "created_at",
        "updated_at",
    },
    "curriculum_derive_job": {
        "id",
        "subject",
        "graph_job_id",
        "status",
        "progress",
        "current_step",
        "error_message",
        "created_at",
        "updated_at",
    },
}


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


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = :table_name"
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _validate_runtime_schema(engine) -> None:
    """开发阶段直接校验 schema，不再兼容旧库自动迁移。"""

    with engine.connect() as conn:
        for table_name, required_columns in _SCHEMA_REQUIREMENTS.items():
            if not _table_exists(conn, table_name):
                continue
            existing_columns = _get_table_columns(conn, table_name)
            missing_columns = sorted(required_columns - existing_columns)
            if not missing_columns:
                continue
            logger.error(
                "database_schema_outdated",
                table_name=table_name,
                missing_columns=missing_columns,
                existing_columns=sorted(existing_columns),
            )
            raise RuntimeError(
                "当前开发数据库 schema 已过期。"
                f"表 `{table_name}` 缺少字段: {', '.join(missing_columns)}。"
                "请删除 `backend/data/aiteachme.db` 或对应 data 目录下数据库后重启服务。"
            )


def init_db() -> None:
    """初始化数据库与向量表。"""

    from app import models as _  # noqa: F401

    engine = get_engine()
    settings = get_settings()

    SQLModel.metadata.create_all(engine)
    _validate_runtime_schema(engine)

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
    """返回一个新的数据库会话。

    .. deprecated:: 0.3.0
        优先使用 ``managed_session()`` 上下文管理器，它提供自动 commit/rollback/close。
    """

    return Session(get_engine())


@contextmanager
def managed_session() -> Generator[Session, None, None]:
    """安全的 session 上下文管理器：成功时 commit，异常时 rollback，最终 close。"""

    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
