from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import exams as exams_api
from app.api import profile as profile_api
from app.api.deps import CurrentUserContext
import app.models  # noqa: F401 - register SQLModel tables
from app.models import (
    Course,
    ExamPaper,
    ExamPaperItem,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    User,
    UserKnowledgeState,
)
from app.models.knowledge_unit import KnowledgeUnit
from app.utils.time import utcnow
from app.workflows.examine.exam_grade.lib.grader import ExamItemGradeDecision
from app.workflows.interact.chat.lib import retrieval as chat_retrieval
from app.workflows.profile.common.lib.mastery import update_mastery_from_exam


COURSE_ID = "course_profrel00000"
USER_ID = "user-profile-reliability"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _seed_user_course(session: Session) -> None:
    session.add(User(id=USER_ID, username=USER_ID))
    session.add(Course(id=COURSE_ID, user_id=USER_ID, name="Profile Reliability"))
    session.commit()


def _seed_template(session: Session) -> tuple[KnowledgeUnit, QuestionTemplate]:
    unit = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="Vectors",
        normalized_name="vectors",
        summary="Vector basics.",
        status="active",
    )
    template = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="single_choice",
        difficulty="easy",
        stem="Which object is a vector?",
        stem_hash="profile-reliability-vector",
        answer="A directed quantity",
        explanation="Vectors have magnitude and direction.",
    )
    session.add_all([unit, template])
    session.commit()
    session.refresh(unit)
    session.refresh(template)
    return unit, template


def _seed_graded_paper(session: Session) -> tuple[ExamPaper, ExamPaperItem, KnowledgeUnit]:
    _seed_user_course(session)
    unit, template = _seed_template(session)
    paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="graded",
        total_items=1,
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    item = ExamPaperItem(
        exam_paper_id=int(paper.id or 0),
        question_template_id=int(template.id or 0),
        item_order=1,
        stem_snapshot=template.stem,
        answer_snapshot=template.answer,
        explanation_snapshot=template.explanation,
        difficulty=template.difficulty,
        question_type=template.question_type,
        score=1.0,
        answer_content="A directed quantity",
        is_correct=True,
        score_obtained=1.0,
        score_max=1.0,
        answered_at=utcnow(),
        graded_at=utcnow(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    session.add(
        QuestionKnowledgeUnitLink(
            exam_paper_item_id=int(item.id or 0),
            knowledge_unit_id=int(unit.id or 0),
            coverage_weight=1.0,
        )
    )
    session.commit()
    return paper, item, unit


def test_update_mastery_from_exam_is_idempotent_per_paper(session: Session) -> None:
    paper, _item, unit = _seed_graded_paper(session)

    first = update_mastery_from_exam(session, int(paper.id or 0))
    state = session.get(UserKnowledgeState, first.updated_state_ids[0])
    assert state is not None
    first_stats = json.loads(state.stats_json)

    second = update_mastery_from_exam(session, int(paper.id or 0))
    session.refresh(state)
    second_stats = json.loads(state.stats_json)

    assert first.states_updated == 1
    assert first.already_consumed is False
    assert second.states_updated == 0
    assert second.updated_state_ids == []
    assert second.already_consumed is True
    assert state.knowledge_unit_id == unit.id
    assert state.total_attempts == 1
    assert state.correct_attempts == 1
    assert state.state_version == 1
    assert first_stats["consumed_exam_paper_ids"] == [paper.id]
    assert second_stats["consumed_exam_paper_ids"] == [paper.id]


@pytest.mark.anyio
async def test_grade_exam_records_profile_update_failure_without_blocking(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_user_course(session)
    _unit, template = _seed_template(session)
    paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="submitted",
        total_items=1,
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    session.add(
        ExamPaperItem(
            exam_paper_id=int(paper.id or 0),
            question_template_id=int(template.id or 0),
            item_order=1,
            stem_snapshot=template.stem,
            answer_snapshot=template.answer,
            explanation_snapshot=template.explanation,
            difficulty=template.difficulty,
            question_type=template.question_type,
            score=1.0,
            answer_content="wrong",
            answered_at=utcnow(),
        )
    )
    session.commit()

    async def fake_run_exam_grade_workflow(**_kwargs):
        return [
            ExamItemGradeDecision(
                is_correct=False,
                score_obtained=0.0,
                score_max=1.0,
                feedback_text="Incorrect.",
                error_cause_label="concept_gap",
                grading_mode="objective_rule",
            )
        ]

    async def fake_profile_update_workflow(**_kwargs):
        return SimpleNamespace(
            failed=True,
            error="update_mastery_failed: secret-provider-token",
            require_value=lambda: {},
        )

    monkeypatch.setattr(exams_api, "run_exam_grade_workflow", fake_run_exam_grade_workflow)
    monkeypatch.setattr(exams_api, "run_profile_update_workflow", fake_profile_update_workflow)

    response = await exams_api._grade_exam(session, paper)
    session.refresh(paper)
    profile_update = json.loads(paper.selection_context_json)["profile_update"]

    assert response.status == "completed"
    assert response.mastery_consumed is False
    assert profile_update["status"] == "failed"
    assert profile_update["attempt_count"] == 1
    assert profile_update["states_updated"] == 0
    assert profile_update["review_task_count"] == 0
    assert profile_update["last_error_code"] == "update_mastery_failed"
    assert "secret-provider-token" not in json.dumps(profile_update)


@pytest.mark.anyio
async def test_grade_exam_records_profile_update_exception_without_blocking(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_user_course(session)
    _unit, template = _seed_template(session)
    paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="submitted",
        total_items=1,
    )
    session.add(paper)
    session.commit()
    session.refresh(paper)
    session.add(
        ExamPaperItem(
            exam_paper_id=int(paper.id or 0),
            question_template_id=int(template.id or 0),
            item_order=1,
            stem_snapshot=template.stem,
            answer_snapshot=template.answer,
            explanation_snapshot=template.explanation,
            difficulty=template.difficulty,
            question_type=template.question_type,
            score=1.0,
            answer_content="wrong",
            answered_at=utcnow(),
        )
    )
    session.commit()

    async def fake_run_exam_grade_workflow(**_kwargs):
        return [
            ExamItemGradeDecision(
                is_correct=False,
                score_obtained=0.0,
                score_max=1.0,
                feedback_text="Incorrect.",
                error_cause_label="concept_gap",
                grading_mode="objective_rule",
            )
        ]

    async def fake_profile_update_workflow(**_kwargs):
        raise RuntimeError("secret-provider-token")

    monkeypatch.setattr(exams_api, "run_exam_grade_workflow", fake_run_exam_grade_workflow)
    monkeypatch.setattr(exams_api, "run_profile_update_workflow", fake_profile_update_workflow)

    response = await exams_api._grade_exam(session, paper)
    session.refresh(paper)
    profile_update = json.loads(paper.selection_context_json)["profile_update"]

    assert response.status == "completed"
    assert response.mastery_consumed is False
    assert profile_update["status"] == "failed"
    assert profile_update["attempt_count"] == 1
    assert profile_update["last_error_code"] == "RuntimeError"
    assert "secret-provider-token" not in json.dumps(profile_update)


@pytest.mark.anyio
async def test_complete_review_refreshes_persisted_profiles(session: Session) -> None:
    _seed_user_course(session)
    unit, _template = _seed_template(session)
    state = UserKnowledgeState(
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=int(unit.id or 0),
        mastery_score=0.35,
        confidence_score=0.4,
        stability_score=0.2,
        review_priority=0.8,
        total_attempts=3,
        correct_attempts=1,
        review_status="pending",
        scheduled_review_at=utcnow(),
        review_reason="repeated_wrong",
    )
    session.add(state)
    session.commit()
    session.refresh(state)

    response = await profile_api.complete_review(
        course_id=COURSE_ID,
        task_id=int(state.id or 0),
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )
    course = session.get(Course, COURSE_ID)
    user = session.get(User, USER_ID)
    assert course is not None
    assert user is not None
    course_profile = json.loads(course.profile_json)
    user_profile = json.loads(user.profile_json)

    assert response.data is not None
    assert response.data.status == "completed"
    assert course_profile["pending_review_count"] == 0
    assert course_profile["due_review_count"] == 0
    assert user_profile["pending_review_count"] == 0
    assert user_profile["due_review_count"] == 0


def test_interact_mastery_lookup_uses_knowledge_unit_target(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_knowledge_states(_session, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(chat_retrieval.profile_repo, "list_knowledge_states", fake_list_knowledge_states)

    assert chat_retrieval._mastery_by_unit_id(object(), course_id=COURSE_ID, user_id=USER_ID) == {}
    assert captured["target_kind"] == "knowledge_unit"
