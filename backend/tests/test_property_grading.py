"""
属性测试：判分完整性（Property 7: Grading Completeness）

验证：
- n 个答案产生 n 个 AnswerRecord
- 每个错误答案恰好产生一个 Mistake 且 analysis 非空
- score = correct_count / total × 100
"""

import os
import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import sqlite_vec
import sqlalchemy as sa
from sqlmodel import SQLModel, Session, create_engine

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.repositories.models import (
    Exam,
    Question,
    QuestionType,
    Difficulty,
)
from app.ai.examine.grader import grade_exam

# ═══════════════════════════════════════════════════════════════
# Plain data containers (avoid detached ORM issues)
# ═══════════════════════════════════════════════════════════════


@dataclass
class GradeResult:
    score: float
    num_records: int
    wrong_record_ids: set[int]
    correct_record_ids: set[int]
    mistake_record_links: list[int]  # answer_record_id per mistake
    mistake_analyses: list[str]


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


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

_non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=1,
    max_size=50,
).map(str.strip).filter(lambda s: len(s) > 0)

_difficulty = st.sampled_from([d.value for d in Difficulty])


@st.composite
def objective_question_and_answer(draw, key: str = "q1"):
    """Generate an objective question with a user answer.

    Returns (Question kwargs dict, user_answer_str, expected_is_correct).
    """
    q_type = draw(st.sampled_from([QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value]))

    if q_type == QuestionType.SINGLE_CHOICE.value:
        options = draw(st.lists(_non_empty_text, min_size=2, max_size=5, unique_by=str.lower))
        correct_answer = draw(st.sampled_from(options))
        is_correct = draw(st.booleans())
        if is_correct:
            user_answer = correct_answer
        else:
            wrong_options = [o for o in options if o.strip().lower() != correct_answer.strip().lower()]
            if wrong_options:
                user_answer = draw(st.sampled_from(wrong_options))
            else:
                user_answer = correct_answer + "_wrong"
    else:
        options = None
        correct_answer = draw(_non_empty_text)
        is_correct = draw(st.booleans())
        user_answer = correct_answer if is_correct else correct_answer + "_wrong"

    q_kwargs = dict(
        question_key=key,
        type=q_type,
        stem=draw(_non_empty_text),
        options=options,
        answer=correct_answer,
        explanation=draw(_non_empty_text),
        knowledge_point=draw(_non_empty_text),
        difficulty=draw(_difficulty),
    )
    return q_kwargs, user_answer, is_correct


@st.composite
def exam_with_answers(draw):
    """Generate 1-15 objective questions with user answers."""
    n = draw(st.integers(min_value=1, max_value=15))
    return [draw(objective_question_and_answer(key=f"q{i + 1}")) for i in range(n)]


# ═══════════════════════════════════════════════════════════════
# Shared helper — eagerly extract data before closing session
# ═══════════════════════════════════════════════════════════════


def _setup_and_grade(questions_data) -> GradeResult:
    """Create fresh DB, insert exam + questions, run grade_exam, return plain results."""
    session = _make_session()

    exam = Exam(subject="test")
    session.add(exam)
    session.commit()
    session.refresh(exam)

    db_questions: list[Question] = []
    for q_kwargs, _, _ in questions_data:
        q = Question(exam_id=exam.id, **q_kwargs)
        session.add(q)
        session.commit()
        session.refresh(q)
        db_questions.append(q)

    answers = {q.question_key: ua for (_, ua, _), q in zip(questions_data, db_questions)}

    mock_analysis = "错因分析：知识点掌握不足，建议复习相关内容。"
    with patch("app.ai.examine.grader.update_profiles_from_grading"):
        with patch("app.ai.examine.grader.acompletion", new_callable=AsyncMock, return_value=mock_analysis):
            submission, records, mistakes = _run_async(
                grade_exam(
                    session,
                    exam_id=exam.id,
                    subject="test",
                    questions=db_questions,
                    answers=answers,
                )
            )

    # Eagerly extract all data while session is still open
    result = GradeResult(
        score=submission.score,
        num_records=len(records),
        wrong_record_ids={r.id for r in records if not r.is_correct},
        correct_record_ids={r.id for r in records if r.is_correct},
        mistake_record_links=[m.answer_record_id for m in mistakes],
        mistake_analyses=[m.analysis for m in mistakes],
    )
    session.close()
    return result


# ═══════════════════════════════════════════════════════════════
# Property 7: n answers → n AnswerRecords
# ═══════════════════════════════════════════════════════════════


@given(data=exam_with_answers())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_n_answers_produce_n_records(data):
    """P7: Submitting n answers must produce exactly n AnswerRecords."""
    result = _setup_and_grade(data)
    assert result.num_records == len(data), (
        f"Expected {len(data)} AnswerRecords, got {result.num_records}"
    )


# ═══════════════════════════════════════════════════════════════
# Property 7: Each wrong answer → exactly one Mistake
# ═══════════════════════════════════════════════════════════════


@given(data=exam_with_answers())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_wrong_answers_produce_mistakes(data):
    """P7: Each incorrect answer must produce exactly one Mistake with non-empty analysis."""
    expected_wrong = sum(1 for _, _, is_correct in data if not is_correct)
    result = _setup_and_grade(data)

    assert len(result.wrong_record_ids) == expected_wrong, (
        f"Expected {expected_wrong} wrong records, got {len(result.wrong_record_ids)}"
    )
    assert len(result.mistake_analyses) == expected_wrong, (
        f"Expected {expected_wrong} Mistakes, got {len(result.mistake_analyses)}"
    )

    # Each mistake has non-empty analysis
    for analysis in result.mistake_analyses:
        assert analysis and analysis.strip(), "Mistake has empty analysis"

    # Each mistake links to a wrong AnswerRecord
    for ar_id in result.mistake_record_links:
        assert ar_id in result.wrong_record_ids, (
            f"Mistake links to record {ar_id} which is not a wrong record"
        )


# ═══════════════════════════════════════════════════════════════
# Property 7: Score = correct_count / total × 100
# ═══════════════════════════════════════════════════════════════


@given(data=exam_with_answers())
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_score_equals_correct_ratio(data):
    """P7: score must equal correct_count / total × 100."""
    n = len(data)
    expected_correct = sum(1 for _, _, is_correct in data if is_correct)
    expected_score = (expected_correct / n * 100) if n > 0 else 0.0

    result = _setup_and_grade(data)
    assert abs(result.score - expected_score) < 0.01, (
        f"Expected score {expected_score}, got {result.score}"
    )


# ═══════════════════════════════════════════════════════════════
# Property 7: All invariants combined
# ═══════════════════════════════════════════════════════════════


@given(data=exam_with_answers())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_grading_completeness_all_invariants(data):
    """P7: Combined — n records, correct mistake count, non-empty analysis, valid score."""
    n = len(data)
    expected_correct = sum(1 for _, _, c in data if c)
    expected_wrong = n - expected_correct

    result = _setup_and_grade(data)

    # n answers → n records
    assert result.num_records == n

    # Wrong count matches
    assert len(result.wrong_record_ids) == expected_wrong
    assert len(result.mistake_analyses) == expected_wrong

    # Each mistake has non-empty analysis and links to a wrong record
    for analysis in result.mistake_analyses:
        assert analysis and analysis.strip()
    for ar_id in result.mistake_record_links:
        assert ar_id in result.wrong_record_ids

    # Score
    expected_score = (expected_correct / n * 100) if n > 0 else 0.0
    assert abs(result.score - expected_score) < 0.01
