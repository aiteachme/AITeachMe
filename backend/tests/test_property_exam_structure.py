"""
属性测试：考试结构不变量（Property 6: Exam Structure Invariant）

验证：
- question_key 在考试内唯一
- type 枚举合法（single_choice / fill_blank / short_answer）
- difficulty 枚举合法（easy / medium / hard）
- single_choice 选项 >= 2 且 answer 在选项中
- knowledge_point 非空
"""

import os

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
os.environ.setdefault("DATA_DIR", "./test_data")

from app.repositories.models import Question, QuestionType, Difficulty
from app.ai.examine.generator import GeneratedQuestion, GeneratedExam, _to_question_models

# ═══════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════

VALID_TYPES = {e.value for e in QuestionType}
VALID_DIFFICULTIES = {e.value for e in Difficulty}

# ═══════════════════════════════════════════════════════════════
# Strategies
# ═══════════════════════════════════════════════════════════════

_non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), blacklist_characters="\x00"),
    min_size=1,
    max_size=100,
).map(str.strip).filter(lambda s: len(s) > 0)

_question_type = st.sampled_from(list(QuestionType))
_difficulty = st.sampled_from(list(Difficulty))


@st.composite
def single_choice_question(draw, key: str = "q1"):
    """Generate a valid single_choice GeneratedQuestion."""
    options = draw(st.lists(_non_empty_text, min_size=2, max_size=6, unique=True))
    answer = draw(st.sampled_from(options))
    return GeneratedQuestion(
        question_key=key,
        type=QuestionType.SINGLE_CHOICE.value,
        stem=draw(_non_empty_text),
        options=options,
        answer=answer,
        explanation=draw(_non_empty_text),
        knowledge_point=draw(_non_empty_text),
        difficulty=draw(_difficulty).value,
    )


@st.composite
def fill_blank_question(draw, key: str = "q1"):
    """Generate a valid fill_blank GeneratedQuestion."""
    return GeneratedQuestion(
        question_key=key,
        type=QuestionType.FILL_BLANK.value,
        stem=draw(_non_empty_text),
        options=None,
        answer=draw(_non_empty_text),
        explanation=draw(_non_empty_text),
        knowledge_point=draw(_non_empty_text),
        difficulty=draw(_difficulty).value,
    )


@st.composite
def short_answer_question(draw, key: str = "q1"):
    """Generate a valid short_answer GeneratedQuestion."""
    return GeneratedQuestion(
        question_key=key,
        type=QuestionType.SHORT_ANSWER.value,
        stem=draw(_non_empty_text),
        options=None,
        answer=draw(_non_empty_text),
        explanation=draw(_non_empty_text),
        knowledge_point=draw(_non_empty_text),
        difficulty=draw(_difficulty).value,
    )


@st.composite
def any_valid_question(draw, key: str = "q1"):
    """Generate any valid GeneratedQuestion."""
    gen = draw(st.sampled_from([
        single_choice_question(key=key),
        fill_blank_question(key=key),
        short_answer_question(key=key),
    ]))
    return draw(gen)


@st.composite
def valid_exam(draw):
    """Generate a GeneratedExam with 1-20 questions, unique keys."""
    n = draw(st.integers(min_value=1, max_value=20))
    questions = []
    for i in range(n):
        q = draw(any_valid_question(key=f"q{i + 1}"))
        questions.append(q)
    return GeneratedExam(questions=questions)


# ═══════════════════════════════════════════════════════════════
# Property 6: question_key uniqueness within an exam
# ═══════════════════════════════════════════════════════════════

@given(exam=valid_exam())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_question_keys_unique(exam: GeneratedExam):
    """P6: question_key must be unique within an exam."""
    questions = _to_question_models(exam)
    keys = [q.question_key for q in questions]
    assert len(keys) == len(set(keys)), (
        f"Duplicate question_keys found: {keys}"
    )


# ═══════════════════════════════════════════════════════════════
# Property 6: type enum validity
# ═══════════════════════════════════════════════════════════════

@given(exam=valid_exam())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_question_type_is_valid_enum(exam: GeneratedExam):
    """P6: After _to_question_models, every question.type is a valid QuestionType."""
    questions = _to_question_models(exam)
    for q in questions:
        assert q.type in VALID_TYPES, (
            f"Invalid question type '{q.type}', expected one of {VALID_TYPES}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 6: difficulty enum validity
# ═══════════════════════════════════════════════════════════════

@given(exam=valid_exam())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_question_difficulty_is_valid_enum(exam: GeneratedExam):
    """P6: After _to_question_models, every question.difficulty is a valid Difficulty."""
    questions = _to_question_models(exam)
    for q in questions:
        assert q.difficulty in VALID_DIFFICULTIES, (
            f"Invalid difficulty '{q.difficulty}', expected one of {VALID_DIFFICULTIES}"
        )


# ═══════════════════════════════════════════════════════════════
# Property 6: single_choice options >= 2 and answer in options
# ═══════════════════════════════════════════════════════════════

@given(exam=valid_exam())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_single_choice_options_and_answer(exam: GeneratedExam):
    """P6: single_choice questions must have >= 2 options and answer must be in options."""
    questions = _to_question_models(exam)
    for q in questions:
        if q.type == QuestionType.SINGLE_CHOICE.value:
            assert q.options is not None, (
                f"single_choice question '{q.question_key}' has no options"
            )
            assert len(q.options) >= 2, (
                f"single_choice question '{q.question_key}' has {len(q.options)} options, need >= 2"
            )
            assert q.answer in q.options, (
                f"single_choice answer '{q.answer}' not in options {q.options}"
            )


# ═══════════════════════════════════════════════════════════════
# Property 6: knowledge_point non-empty
# ═══════════════════════════════════════════════════════════════

@given(exam=valid_exam())
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_knowledge_point_non_empty(exam: GeneratedExam):
    """P6: Every question must have a non-empty knowledge_point."""
    questions = _to_question_models(exam)
    for q in questions:
        assert q.knowledge_point and q.knowledge_point.strip(), (
            f"Question '{q.question_key}' has empty knowledge_point"
        )


# ═══════════════════════════════════════════════════════════════
# Property 6: Robustness — invalid type/difficulty get normalized
# ═══════════════════════════════════════════════════════════════

@given(
    bad_type=st.text(min_size=1, max_size=30).filter(lambda s: s not in VALID_TYPES),
    bad_diff=st.text(min_size=1, max_size=30).filter(lambda s: s not in VALID_DIFFICULTIES),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_invalid_type_difficulty_normalized(bad_type: str, bad_diff: str):
    """P6: _to_question_models normalizes invalid type/difficulty to valid defaults."""
    gq = GeneratedQuestion(
        question_key="q1",
        type=bad_type,
        stem="Test stem",
        options=None,
        answer="Test answer",
        explanation="Test explanation",
        knowledge_point="Test KP",
        difficulty=bad_diff,
    )
    exam = GeneratedExam(questions=[gq])
    questions = _to_question_models(exam)

    assert len(questions) == 1
    q = questions[0]
    assert q.type in VALID_TYPES, f"Normalized type '{q.type}' still invalid"
    assert q.difficulty in VALID_DIFFICULTIES, f"Normalized difficulty '{q.difficulty}' still invalid"


# ═══════════════════════════════════════════════════════════════
# Property 6: All invariants combined on a single exam
# ═══════════════════════════════════════════════════════════════

@given(exam=valid_exam())
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_exam_structure_all_invariants(exam: GeneratedExam):
    """P6: Combined check — all structural invariants hold simultaneously."""
    questions = _to_question_models(exam)

    # At least one question
    assert len(questions) >= 1

    # Unique keys
    keys = [q.question_key for q in questions]
    assert len(keys) == len(set(keys)), f"Duplicate keys: {keys}"

    for q in questions:
        # Valid enums
        assert q.type in VALID_TYPES
        assert q.difficulty in VALID_DIFFICULTIES

        # single_choice constraints
        if q.type == QuestionType.SINGLE_CHOICE.value:
            assert q.options is not None and len(q.options) >= 2
            assert q.answer in q.options

        # knowledge_point non-empty
        assert q.knowledge_point and q.knowledge_point.strip()
