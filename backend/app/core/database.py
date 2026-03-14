"""
SQLite 引擎初始化、sqlite-vec 扩展加载、会话工厂

单一引擎连接 data/aiteachme.db，所有学科数据通过 WHERE subject = ? 隔离。
"""

import sqlite_vec
import sqlalchemy as sa
import structlog
from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

from app.core.config import get_settings

logger = structlog.get_logger()

_engine = None


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
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    logger.info("database_engine_created", db_path=str(db_path))
    return _engine


def init_db() -> None:
    """创建所有 SQLModel 表和 chunk_embeddings 向量虚表。"""
    # 延迟导入，避免循环依赖（models 依赖 SQLModel，SQLModel 需要 engine 已存在）
    from app.repositories import models as _  # noqa: F401

    engine = get_engine()
    settings = get_settings()

    SQLModel.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(
            sa.text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
                f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{settings.embedding_dim}])"
            )
        )
        conn.commit()

    logger.info("database_initialized", embedding_dim=settings.embedding_dim)


def get_session() -> Session:
    """创建并返回一个新的数据库 Session（调用方负责关闭）。"""
    return Session(get_engine())
