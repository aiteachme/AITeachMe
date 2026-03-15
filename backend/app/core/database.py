"""
SQLite 引擎初始化、sqlite-vec 扩展加载、会话工厂。

单一引擎连接 data/aiteachme.db，所有学科数据通过 WHERE subject = ? 隔离。

注意：
- 某些托管环境（例如部分云平台的 Python 构建）不暴露
  `sqlite3.Connection.enable_load_extension`
- 在这些环境下，应用仍应能够启动
- 如果 sqlite-vec 无法启用，则只禁用向量相关能力，而不是让整个服务启动失败
"""

from __future__ import annotations

import sys

try:
    import pysqlite3 as sqlite3  # type: ignore[import-not-found]

    sys.modules["sqlite3"] = sqlite3
    _SQLITE_DRIVER = "pysqlite3-binary"
except ImportError:
    import sqlite3  # noqa: F401

    _SQLITE_DRIVER = "stdlib-sqlite3"

import sqlite_vec
import sqlalchemy as sa
import structlog
from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import get_settings
from app.core.exceptions import VectorExtensionUnavailableError

logger = structlog.get_logger()

_engine = None
_vec_ready: bool | None = None
_vec_error: str | None = None


def _set_vec_status(ready: bool, error: str | None = None) -> None:
    """Persist the current sqlite-vec availability for the running process."""

    global _vec_ready, _vec_error
    _vec_ready = ready
    _vec_error = error


def is_vec_ready() -> bool:
    """Return whether sqlite-vec is available in the current process."""

    return bool(_vec_ready)


def require_vec_ready() -> None:
    """Raise a user-facing error when sqlite-vec is unavailable."""

    if not is_vec_ready():
        raise VectorExtensionUnavailableError(_vec_error or "")


def get_vec_status() -> tuple[bool | None, str | None]:
    """Return the current sqlite-vec status tuple `(ready, error)`."""

    return _vec_ready, _vec_error


def _load_vec_extension(dbapi_conn) -> None:
    """Attempt to load sqlite-vec on a fresh DB-API connection.

    Some environments expose `enable_load_extension`, while others do not.
    We therefore try the safest available path and degrade gracefully when
    the extension cannot be enabled.
    """

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
    """获取或创建单一 SQLite engine（懒初始化，线程安全）。"""
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


def init_db() -> None:
    """创建所有 SQLModel 表，并在可用时初始化 sqlite-vec 虚表。"""
    # 延迟导入，避免循环依赖（models 依赖 SQLModel，SQLModel 需要 engine 已存在）
    from app.repositories import models as _  # noqa: F401

    engine = get_engine()
    settings = get_settings()

    SQLModel.metadata.create_all(engine)

    if is_vec_ready():
        with engine.connect() as conn:
            conn.execute(
                sa.text(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
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
    """创建并返回一个新的数据库 Session（调用方负责关闭）。"""
    return Session(get_engine())
