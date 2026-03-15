"""
属性测试：掌握度单调性（Property 5: Mastery Monotonicity）

验证：
- 连续正确答案 → mastery 非递减
- 连续错误答案 → mastery 非递增
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


@given(
    initial_attempts=st.integers(min_value=1, max_value=100),
    initial_correct=st.integers(min_value=0),
    num_consecutive_correct=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_consecutive_correct_mastery_non_decreasing(
    initial_attempts: int,
    initial_correct: int,
    num_consecutive_correct: int,
):
    """P5: consecutive correct answers → mastery non-decreasing."""
    initial_correct = min(initial_correct, initial_attempts)
    session = _make_session()
    kp = f"mono_correct_{initial_attempts}_{initial_correct}_{num_consecutive_correct}"

    attempts = initial_attempts
    correct = initial_correct

    profile = profile_repo.upsert_profile(
        session,
        user_id="local",
        subject="math",
        knowledge_point=kp,
        attempts=attempts,
        correct=correct,
    )
    prev_mastery = profile.mastery
    assert prev_mastery is not None

    for _ in range(num_consecutive_correct):
        attempts += 1
        correct += 1
        profile = profile_repo.upsert_profile(
            session,
            user_id="local",
            subject="math",
            knowledge_point=kp,
            attempts=attempts,
            correct=correct,
        )
        assert profile.mastery is not None
        assert profile.mastery >= prev_mastery - 1e-12, (
            f"mastery decreased: {prev_mastery} -> {profile.mastery}"
        )
        prev_mastery = profile.mastery


@given(
    initial_attempts=st.integers(min_value=1, max_value=100),
    initial_correct=st.integers(min_value=0),
    num_consecutive_wrong=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_consecutive_wrong_mastery_non_increasing(
    initial_attempts: int,
    initial_correct: int,
    num_consecutive_wrong: int,
):
    """P5: consecutive wrong answers → mastery non-increasing."""
    initial_correct = min(initial_correct, initial_attempts)
    session = _make_session()
    kp = f"mono_wrong_{initial_attempts}_{initial_correct}_{num_consecutive_wrong}"

    attempts = initial_attempts
    correct = initial_correct

    profile = profile_repo.upsert_profile(
        session,
        user_id="local",
        subject="math",
        knowledge_point=kp,
        attempts=attempts,
        correct=correct,
    )
    prev_mastery = profile.mastery
    assert prev_mastery is not None

    for _ in range(num_consecutive_wrong):
        attempts += 1
        # correct stays the same (wrong answer)
        profile = profile_repo.upsert_profile(
            session,
            user_id="local",
            subject="math",
            knowledge_point=kp,
            attempts=attempts,
            correct=correct,
        )
        assert profile.mastery is not None
        assert profile.mastery <= prev_mastery + 1e-12, (
            f"mastery increased: {prev_mastery} -> {profile.mastery}"
        )
        prev_mastery = profile.mastery
