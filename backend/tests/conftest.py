"""
共享测试夹具：内存 SQLite 引擎、db_session、Settings override
"""

import os
import pytest
import sqlite_vec
import sqlalchemy as sa
from sqlmodel import SQLModel, Session, create_engine

# 设置测试环境变量（必须在导入 app 模块之前）
os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")


@pytest.fixture(name="engine")
def engine_fixture():
    """内存 SQLite 引擎，加载 sqlite-vec 扩展。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    @sa.event.listens_for(engine, "connect")
    def load_vec(dbapi_conn, connection_record):
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    # 导入 models 以注册所有表
    from app.repositories import models as _  # noqa: F401

    SQLModel.metadata.create_all(engine)

    # 创建向量虚表
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
            "USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[1536])"
        ))
        conn.commit()

    yield engine
    engine.dispose()


@pytest.fixture(name="session")
def session_fixture(engine):
    """每个测试独立的数据库 Session。"""
    with Session(engine) as session:
        yield session
