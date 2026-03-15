"""
属性测试：掌握度计算（Property 4: Mastery Computation）

验证：
- mastery = correct / attempts（attempts > 0 时）
- mastery = None（attempts == 0 时）
- 0.0 <= mastery <= 1.0
"""

import os

import sqlite_vec
import sqlalchemy as sa
from sqlmodel import SQLModel, Session, create_engine

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.repositories import profile_repo


# ═══════════════════════════════════════════════════════════════
# DB helper
# ═══════════════════════════════════════════════════════════════


def _make_session() -> Session:
    """Create a fresh in-memory SQLite session with sqlite-vec loaded."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    @sa.event.listens_for(engine, "connect")
    def _load_vec(dbapi_conn, _):
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings "
            "USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[1536])"
        ))
        conn.commit()
    return Session(engine)


# ═══════════════════════════════════════════════════════════════
# Property tests
# ═══════════════════════════════════════════════════════════════


@given(
    attempts=st.integers(min_value=1, max_value=10000),
    correct=st.integers(min_value=0),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_mastery_equals_correct_over_attempts(attempts: int, correct: int):
    """P4: mastery = correct / attempts when attempts > 0."""
    correct = min(correct, attempts)  # correct <= attempts
    session = _make_session()
    profile = profile_repo.upsert_profile(
        session,
        user_id="local",
        subject="math",
        knowledge_point=f"kp_{attempts}_{correct}",
        attempts=attempts,
        correct=correct,
    )
    expected = correct / attempts
    assert profile.mastery is not None
    assert abs(profile.mastery - expected) < 1e-9


@given(data=st.data())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_mastery_is_none_when_zero_attempts(data):
    """P4: mastery = None when attempts == 0."""
    session = _make_session()
    kp = data.draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1, max_size=20,
    ))
    profile = profile_repo.upsert_profile(
        session,
        user_id="local",
        subject="math",
        knowledge_point=kp,
        attempts=0,
        correct=0,
    )
    assert profile.mastery is None
    assert profile.attempts == 0
    assert profile.correct == 0


@given(
    attempts=st.integers(min_value=1, max_value=10000),
    correct=st.integers(min_value=0),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_mastery_bounded_zero_to_one(attempts: int, correct: int):
    """P4: 0.0 <= mastery <= 1.0 for all valid inputs."""
    correct = min(correct, attempts)
    session = _make_session()
    profile = profile_repo.upsert_profile(
        session,
        user_id="local",
        subject="science",
        knowledge_point=f"bound_{attempts}_{correct}",
        attempts=attempts,
        correct=correct,
    )
    assert profile.mastery is not None
    assert 0.0 <= profile.mastery <= 1.0


@given(
    attempts=st.integers(min_value=0, max_value=500),
    correct=st.integers(min_value=0),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_mastery_all_invariants_combined(attempts: int, correct: int):
    """P4 combined: all mastery invariants in a single pass."""
    correct = min(correct, attempts)
    session = _make_session()
    profile = profile_repo.upsert_profile(
        session,
        user_id="local",
        subject="history",
        knowledge_point=f"combined_{attempts}_{correct}",
        attempts=attempts,
        correct=correct,
    )

    if attempts == 0:
        assert profile.mastery is None
    else:
        assert profile.mastery is not None
        assert abs(profile.mastery - correct / attempts) < 1e-9
        assert 0.0 <= profile.mastery <= 1.0
