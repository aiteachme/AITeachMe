"""
共享测试夹具：内存 SQLite 引擎、db_session、FastAPI TestClient（含依赖覆盖）、Mock LLM
"""

import os
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
import sqlite_vec
import sqlalchemy as sa
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlmodel import SQLModel, Session, create_engine

# 设置测试环境变量（必须在导入 app 模块之前）
os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")


# ═══════════════════════════════════════════════════════════════
# 数据库夹具
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(name="engine")
def engine_fixture():
    """内存 SQLite 引擎，加载 sqlite-vec 扩展。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    @sa.event.listens_for(engine, "connect")
    def load_vec(dbapi_conn, connection_record):
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    from app.repositories import models as _  # noqa: F401

    SQLModel.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
            "USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[1536])"
        ))
        conn.commit()

    yield engine
    engine.dispose()


@pytest.fixture(name="session")
def session_fixture(engine) -> Generator[Session, None, None]:
    """每个测试独立的数据库 Session。"""
    with Session(engine) as session:
        yield session


# ═══════════════════════════════════════════════════════════════
# FastAPI TestClient 夹具（含依赖覆盖）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(name="client")
def client_fixture(engine) -> Generator[TestClient, None, None]:
    """同步 TestClient，覆盖 DB session 和数据库初始化。"""
    from app.api.deps import get_db
    from app.main import app

    def _override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture(name="async_client")
async def async_client_fixture(engine) -> AsyncClient:
    """异步 TestClient，用于测试 SSE 流式端点等异步场景。"""
    from app.api.deps import get_db
    from app.main import app

    def _override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
# Mock LLM 夹具（确定性测试，不调用真实 LLM）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(name="mock_llm")
def mock_llm_fixture():
    """Mock acompletion，返回可配置的固定文本。

    用法：
        def test_something(mock_llm):
            mock_llm.return_value = "自定义回复"
            # ... 调用依赖 LLM 的代码
    """
    with patch("app.core.llm.litellm.acompletion", new_callable=AsyncMock) as mock:
        # 默认返回一个类 LiteLLM 响应结构
        mock.return_value = _make_llm_response("这是一个测试回复。")
        yield mock


@pytest.fixture(name="mock_llm_structured")
def mock_llm_structured_fixture():
    """Mock acompletion_structured，返回可配置的 Pydantic 模型实例。

    用法：
        def test_something(mock_llm_structured):
            mock_llm_structured.return_value = MyModel(field="value")
            # ... 调用依赖结构化输出的代码
    """
    with patch("app.core.llm.instructor.from_litellm") as mock_from:
        mock_client = AsyncMock()
        mock_from.return_value = mock_client
        # 调用方通过 mock_client.chat.completions.create.return_value 设置返回值
        yield mock_client.chat.completions.create


@pytest.fixture(name="mock_embedding")
def mock_embedding_fixture():
    """Mock aembed_texts，返回固定维度的零向量。

    用法：
        def test_something(mock_embedding):
            mock_embedding.return_value = [[0.1] * 1536]
            # ... 调用依赖 embedding 的代码
    """
    with patch("app.core.embedding.litellm.aembedding", new_callable=AsyncMock) as mock:
        mock.return_value = _make_embedding_response([[0.0] * 1536])
        yield mock


# ═══════════════════════════════════════════════════════════════
# 辅助函数 — 构造 mock 响应对象
# ═══════════════════════════════════════════════════════════════


def _make_llm_response(content: str):
    """构造一个类 LiteLLM acompletion 响应对象。"""

    class _Delta:
        def __init__(self, c: str):
            self.content = c

    class _Choice:
        def __init__(self, c: str):
            self.message = _Delta(c)
            self.delta = _Delta(c)

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 20
        total_tokens = 30

        def model_dump(self):
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            }

    class _Response:
        def __init__(self, c: str):
            self.choices = [_Choice(c)]
            self.usage = _Usage()

    return _Response(content)


def _make_embedding_response(vectors: list[list[float]]):
    """构造一个类 LiteLLM aembedding 响应对象。"""

    class _Usage:
        prompt_tokens = 5
        total_tokens = 5

        def model_dump(self):
            return {"prompt_tokens": self.prompt_tokens, "total_tokens": self.total_tokens}

    class _Response:
        def __init__(self, vecs: list[list[float]]):
            self.data = [{"embedding": v} for v in vecs]
            self.usage = _Usage()

    return _Response(vectors)
