"""
属性测试：学科数据隔离（Property 9 — Subject Data Isolation）

验证对学科 s1 的写入不影响学科 s2 的查询。
覆盖 RawFile、Knowledge、ChatMessage、UserProfile、Exam 五个维度。

验证需求：2.6
"""

import os

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

import sqlite_vec
import sqlalchemy as sa
from sqlmodel import SQLModel, Session, create_engine

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.repositories.models import (
    RawFile,
    Knowledge,
    ChatMessage,
    Exam,
    Question,
    ExamSubmission,
    AnswerRecord,
    Mistake,
    ParseStatus,
    PipelineStage,
)
from app.repositories import (
    ingest_repo,
    knowledge_repo,
    chat_repo,
    exam_repo,
    profile_repo,
)


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
# Strategies — generate distinct subject pairs
# ═══════════════════════════════════════════════════════════════

subject_st = st.from_regex(r"[a-z][a-z0-9_-]{0,15}", fullmatch=True)

distinct_subjects_st = st.tuples(subject_st, subject_st).filter(lambda t: t[0] != t[1])


# ═══════════════════════════════════════════════════════════════
# Property tests
# ═══════════════════════════════════════════════════════════════


@given(subjects=distinct_subjects_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_rawfile_isolation(subjects):
    """Writing RawFile to s1 does not appear in s2 queries."""
    s1, s2 = subjects
    session = _make_session()

    # Write to s1
    rf = ingest_repo.create_raw_file(session, RawFile(
        subject=s1, filename="test.pdf", filetype="pdf",
        file_path="/tmp/test.pdf", parse_status=ParseStatus.PENDING,
    ))
    assert rf.id is not None

    # Query s2 — should be empty
    items_s2, total_s2 = ingest_repo.list_raw_files_by_subject(session, s2)
    assert total_s2 == 0
    assert items_s2 == []

    # Query s1 — should have the record
    items_s1, total_s1 = ingest_repo.list_raw_files_by_subject(session, s1)
    assert total_s1 == 1
    assert items_s1[0].id == rf.id


@given(subjects=distinct_subjects_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_knowledge_isolation(subjects):
    """Writing Knowledge to s1 does not appear in s2 queries."""
    s1, s2 = subjects
    session = _make_session()

    # Create prerequisite RawFile
    rf = ingest_repo.create_raw_file(session, RawFile(
        subject=s1, filename="doc.pdf", filetype="pdf",
        file_path="/tmp/doc.pdf", parse_status=ParseStatus.PARSED,
    ))

    # Write Knowledge to s1
    k = knowledge_repo.create_knowledge(session, Knowledge(
        subject=s1, raw_file_id=rf.id, title="Test Doc",
        markdown_content="# Hello", pipeline_stage=PipelineStage.EMBEDDED,
    ))
    assert k.id is not None

    # Query s2 — should be empty
    items_s2, total_s2 = knowledge_repo.list_knowledge_by_subject(session, s2)
    assert total_s2 == 0
    assert items_s2 == []

    # Query s1 — should have the record
    items_s1, total_s1 = knowledge_repo.list_knowledge_by_subject(session, s1)
    assert total_s1 == 1
    assert items_s1[0].id == k.id


@given(subjects=distinct_subjects_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_chat_message_isolation(subjects):
    """Writing ChatMessage to s1 does not appear in s2 queries."""
    s1, s2 = subjects
    session = _make_session()

    # Write message pair to s1
    user_msg, asst_msg = chat_repo.create_message_pair(
        session, subject=s1,
        user_content="What is AI?",
        assistant_content="AI is artificial intelligence.",
        contexts=[{"chunk_id": 1}],
    )

    # Query s2 — should be empty
    items_s2, total_s2 = chat_repo.list_messages_by_subject(session, s2)
    assert total_s2 == 0
    assert items_s2 == []

    # Recent turns for s2 — should be empty
    recent_s2 = chat_repo.get_recent_turns(session, s2)
    assert recent_s2 == []

    # Query s1 — should have 2 messages
    items_s1, total_s1 = chat_repo.list_messages_by_subject(session, s1)
    assert total_s1 == 2


@given(subjects=distinct_subjects_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_profile_isolation(subjects):
    """Writing UserProfile to s1 does not appear in s2 queries."""
    s1, s2 = subjects
    session = _make_session()

    # Write profile to s1
    profile_repo.upsert_profile(
        session, user_id="local", subject=s1,
        knowledge_point="linear-algebra", attempts=10, correct=7,
    )

    # Query s2 — should be empty
    items_s2, total_s2 = profile_repo.list_profiles_by_subject(session, s2)
    assert total_s2 == 0
    assert items_s2 == []

    # Weak points for s2 — should be empty
    weak_s2 = profile_repo.get_weak_points(session, s2)
    assert weak_s2 == []

    # Query s1 — should have the record
    items_s1, total_s1 = profile_repo.list_profiles_by_subject(session, s1)
    assert total_s1 == 1
    assert items_s1[0].knowledge_point == "linear-algebra"


@given(subjects=distinct_subjects_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_exam_isolation(subjects):
    """Writing Exam + Question to s1 does not appear in s2 history."""
    s1, s2 = subjects
    session = _make_session()

    # Create exam in s1
    exam = Exam(subject=s1)
    questions = [
        Question(
            exam_id=0, question_key="q1", type="single_choice",
            stem="What is 1+1?", options=["1", "2", "3"],
            answer="2", explanation="Basic math",
            knowledge_point="arithmetic", difficulty="easy",
        ),
    ]
    exam, questions = exam_repo.create_exam_with_questions(session, exam, questions)

    # Query s2 history — should be empty
    items_s2, total_s2 = exam_repo.list_exam_history_by_subject(session, s2)
    assert total_s2 == 0
    assert items_s2 == []

    # Query s1 history — should have the exam
    items_s1, total_s1 = exam_repo.list_exam_history_by_subject(session, s1)
    assert total_s1 == 1
    assert items_s1[0]["exam_id"] == exam.id


@given(subjects=distinct_subjects_st)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_mistake_isolation(subjects):
    """Writing Mistake via exam in s1 does not appear in s2 mistake list."""
    s1, s2 = subjects
    session = _make_session()

    # Create exam + question in s1
    exam = Exam(subject=s1)
    questions = [
        Question(
            exam_id=0, question_key="q1", type="fill_blank",
            stem="Capital of France?", options=None,
            answer="Paris", explanation="Geography",
            knowledge_point="geography", difficulty="easy",
        ),
    ]
    exam, questions = exam_repo.create_exam_with_questions(session, exam, questions)

    # Create submission + answer record
    submission = ExamSubmission(exam_id=exam.id, user_id="local", score=0.0)
    records = [
        AnswerRecord(
            submission_id=0, question_id=questions[0].id,
            user_answer="London", is_correct=False,
        ),
    ]
    submission, records = exam_repo.create_submission_with_records(session, submission, records)

    # Create mistake
    exam_repo.create_mistake(session, Mistake(
        answer_record_id=records[0].id,
        analysis="Confused capital cities",
    ))

    # Query s2 mistakes — should be empty
    items_s2, total_s2 = exam_repo.list_mistakes_by_subject(session, s2)
    assert total_s2 == 0
    assert items_s2 == []

    # Query s1 mistakes — should have the mistake
    items_s1, total_s1 = exam_repo.list_mistakes_by_subject(session, s1)
    assert total_s1 == 1


@given(subjects=distinct_subjects_st)
@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
def test_cross_subject_writes_do_not_interfere(subjects):
    """Writing to both s1 and s2 keeps data correctly isolated."""
    s1, s2 = subjects
    session = _make_session()

    # Write profiles to both subjects
    profile_repo.upsert_profile(
        session, user_id="local", subject=s1,
        knowledge_point="calculus", attempts=5, correct=3,
    )
    profile_repo.upsert_profile(
        session, user_id="local", subject=s2,
        knowledge_point="algebra", attempts=8, correct=6,
    )

    # Each subject sees only its own data
    items_s1, total_s1 = profile_repo.list_profiles_by_subject(session, s1)
    assert total_s1 == 1
    assert items_s1[0].knowledge_point == "calculus"

    items_s2, total_s2 = profile_repo.list_profiles_by_subject(session, s2)
    assert total_s2 == 1
    assert items_s2[0].knowledge_point == "algebra"

    # Write more to s1 — s2 count should not change
    profile_repo.upsert_profile(
        session, user_id="local", subject=s1,
        knowledge_point="geometry", attempts=3, correct=1,
    )

    _, total_s2_after = profile_repo.list_profiles_by_subject(session, s2)
    assert total_s2_after == 1  # unchanged

    items_s1_after, total_s1_after = profile_repo.list_profiles_by_subject(session, s1)
    assert total_s1_after == 2
