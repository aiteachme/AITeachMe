from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
backend_root_str = str(BACKEND_ROOT)
if backend_root_str not in sys.path:
    sys.path.insert(0, backend_root_str)

from app.models import User


@pytest.fixture(autouse=True)
def disable_langsmith_uploads_in_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep pytest runs from polluting the shared LangSmith project with test traces.
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine, expire_on_commit=False) as db_session:
        db_session.add(User(id="local", username="local"))
        db_session.commit()
        yield db_session
