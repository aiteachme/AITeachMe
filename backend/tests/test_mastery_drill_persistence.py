from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import exams as exams_api
from app.api.deps import CurrentUserContext
import app.models  # noqa: F401 - register every SQLModel table
from app.models import (
    Course,
    ExamPaper,
    ExamPaperItem,
    MasteryDrillAttempt,
    MasteryDrillSession,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
)
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import exams_repo
from app.schemas.exams import (
    ExamGenerateRequest,
    ExamSubmitAnswerItem,
    ExamSubmitRequest,
    MasteryDrillAttemptRequest,
    MasteryDrillCompleteRequest,
    MasteryDrillStartRequest,
    QuestionTemplateGradeResponse,
)
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow
from app.workflows.profile.common.lib.mastery import update_mastery_from_exam


COURSE_ID = "course_drill0000000"
USER_ID = "user-drill"


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
def user() -> CurrentUserContext:
    return CurrentUserContext(user_id=USER_ID, email=None, is_local=True)


def _seed_course_and_template(session: Session) -> tuple[QuestionTemplate, KnowledgeUnit]:
    course = Course(id=COURSE_ID, user_id=USER_ID, name="Durable Drill")
    unit = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="Matrix inverse",
        normalized_name="matrix_inverse",
        summary="Understand invertibility.",
        status="active",
    )
    session.add(course)
    session.add(unit)
    session.commit()
    session.refresh(unit)
    template = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="single_choice",
        difficulty="medium",
        stem="Which matrix is invertible?",
        stem_hash="durable-drill-template",
        options_json=json.dumps(["A", "B"]),
        answer="A",
        explanation="A has a non-zero determinant.",
        status="active",
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    session.add(
        QuestionKnowledgeUnitLink(
            question_template_id=int(template.id or 0),
            knowledge_unit_id=int(unit.id or 0),
            coverage_weight=1.0,
        )
    )
    session.commit()
    return template, unit


async def _start(
    session: Session,
    user: CurrentUserContext,
    template: QuestionTemplate,
    *,
    session_key: str = "drill-session-1",
):
    return await exams_api.start_mastery_drill(
        course_id=COURSE_ID,
        body=MasteryDrillStartRequest(
            session_key=session_key,
            question_template_ids=[int(template.id or 0)],
            configured_question_count=1,
            configured_question_types=["single_choice"],
        ),
        user=user,
        session=session,
    )


@pytest.mark.anyio
async def test_mastery_drill_start_is_durable_and_resumes_active_session(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)

    first = await _start(session, user, template)
    resumed = await _start(session, user, template, session_key="another-client-key")

    assert first.data.id == resumed.data.id
    assert first.data.status == "in_progress"
    assert first.data.mastery_drill is not None
    assert first.data.mastery_drill.status == "active"
    assert len(first.data.items) == 1
    assert len(session.exec(select(ExamPaper)).all()) == 1
    assert len(session.exec(select(MasteryDrillSession)).all()) == 1

    active = await exams_api.active_mastery_drill(
        course_id=COURSE_ID,
        user=user,
        session=session,
    )
    assert active.data is not None
    assert active.data.id == first.data.id


@pytest.mark.anyio
async def test_generic_exam_endpoints_reject_mastery_drill_mode(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)

    with pytest.raises(AITeachMeError) as generate_error:
        await exams_api.generate_exam(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
            background_tasks=BackgroundTasks(),
            course_id=COURSE_ID,
            body=ExamGenerateRequest(exam_mode="mastery_drill", num_questions=1),
            user=user,
            session=session,
        )
    assert generate_error.value.error_code == "MASTERY_DRILL_DEDICATED_ENDPOINT_REQUIRED"

    started = await _start(session, user, template)
    item_id = int(started.data.items[0].id)
    with pytest.raises(AITeachMeError) as submit_error:
        await exams_api.submit_exam(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
            background_tasks=BackgroundTasks(),
            course_id=COURSE_ID,
            exam_paper_id=int(started.data.id),
            body=ExamSubmitRequest(
                answers=[ExamSubmitAnswerItem(exam_paper_item_id=item_id, answer="A")],
                submission_key="generic-submit-must-fail",
            ),
            user=user,
            session=session,
        )
    assert submit_error.value.error_code == "MASTERY_DRILL_DEDICATED_ENDPOINT_REQUIRED"


@pytest.mark.anyio
async def test_mastery_drill_start_abandons_inconsistent_active_session(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)
    started = await _start(session, user, template)
    old_paper = session.get(ExamPaper, int(started.data.id))
    assert old_paper is not None
    old_paper.status = "graded"
    session.add(old_paper)
    session.commit()

    replacement = await _start(session, user, template, session_key="replacement-session")
    old_drill = exams_repo.get_mastery_drill_session_by_paper(session, paper_id=int(old_paper.id or 0))

    assert replacement.data.id != old_paper.id
    assert old_drill is not None and old_drill.status == "abandoned"
    assert replacement.data.mastery_drill is not None
    assert replacement.data.mastery_drill.status == "active"


@pytest.mark.anyio
async def test_mastery_drill_database_allows_only_one_active_session_per_user_course(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)
    await _start(session, user, template)

    second_paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="mastery_drill",
        status="in_progress",
        visibility="visible",
        total_items=1,
    )
    session.add(second_paper)
    session.flush()
    session.add(
        MasteryDrillSession(
            exam_paper_id=int(second_paper.id or 0),
            course_id=COURSE_ID,
            user_id=USER_ID,
            session_key="parallel-start",
            status="active",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


@pytest.mark.anyio
async def test_mastery_drill_attempt_lease_can_be_renewed_by_its_owner(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)
    started = await _start(session, user, template)
    item = session.get(ExamPaperItem, int(started.data.items[0].id))
    drill = exams_repo.get_mastery_drill_session_by_paper(session, paper_id=int(started.data.id))
    assert item is not None and drill is not None
    now = utcnow()

    outcome, attempt = exams_repo.claim_mastery_drill_attempt(
        session,
        drill_session_id=int(drill.id or 0),
        item=item,
        attempt_key="lease-owner-attempt",
        request_hash="lease-owner-hash",
        answer="A",
        time_spent_seconds=None,
        hint_used=False,
        confidence_self_report=None,
        claim_token="lease-owner",
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )

    assert outcome == "claimed"
    assert exams_repo.renew_mastery_drill_attempt_lease(
        session,
        attempt_id=int(attempt.id or 0),
        claim_token="lease-owner",
        lease_expires_at=now + timedelta(minutes=10),
    )
    assert not exams_repo.renew_mastery_drill_attempt_lease(
        session,
        attempt_id=int(attempt.id or 0),
        claim_token="another-worker",
        lease_expires_at=now + timedelta(minutes=10),
    )


@pytest.mark.anyio
async def test_mastery_drill_attempts_and_completion_are_idempotent_and_feed_profile(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)
    grade_calls: list[str] = []

    async def fake_grade(*, answer: str, item: ExamPaperItem, **_kwargs):
        grade_calls.append(answer)
        correct = answer == "A"
        return QuestionTemplateGradeResponse(
            question_template_id=int(item.question_template_id or 0),
            question_type=item.question_type,
            is_correct=correct,
            score_obtained=1.0 if correct else 0.0,
            score_max=1.0,
            feedback_text="correct" if correct else "retry",
            error_cause_label=None if correct else "concept_gap",
            grading_mode="objective_rule",
            correct_answer=item.answer_snapshot,
        )

    monkeypatch.setattr(exams_api, "_grade_exam_paper_item_answer", fake_grade)
    started = await _start(session, user, template)
    paper_id = int(started.data.id)
    item_id = int(started.data.items[0].id)

    wrong_request = MasteryDrillAttemptRequest(
        exam_paper_item_id=item_id,
        answer="B",
        attempt_key="wrong-attempt",
        time_spent_seconds=12,
    )
    wrong = await exams_api.record_mastery_drill_attempt(
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=wrong_request,
        user=user,
        session=session,
    )
    wrong_retry = await exams_api.record_mastery_drill_attempt(
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=wrong_request,
        user=user,
        session=session,
    )
    assert wrong.data.id == wrong_retry.data.id
    assert wrong.data.is_correct is False
    assert exams_repo.list_wrong_question_template_ids(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        template_ids=[int(template.id or 0)],
    ) == {int(template.id or 0)}

    correct = await exams_api.record_mastery_drill_attempt(
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=MasteryDrillAttemptRequest(
            exam_paper_item_id=item_id,
            answer="A",
            attempt_key="correct-attempt",
            time_spent_seconds=8,
        ),
        user=user,
        session=session,
    )
    correct_retry = await exams_api.record_mastery_drill_attempt(
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=MasteryDrillAttemptRequest(
            exam_paper_item_id=item_id,
            answer="A",
            attempt_key="correct-attempt",
            time_spent_seconds=8,
        ),
        user=user,
        session=session,
    )

    assert correct.data.is_correct is True
    assert correct_retry.data.id == correct.data.id
    assert grade_calls == ["B", "A"]
    assert exams_repo.list_wrong_question_template_ids(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        template_ids=[int(template.id or 0)],
    ) == set()

    with pytest.raises(AITeachMeError) as passed_error:
        await exams_api.record_mastery_drill_attempt(
            course_id=COURSE_ID,
            exam_paper_id=paper_id,
            body=MasteryDrillAttemptRequest(
                exam_paper_item_id=item_id,
                answer="B",
                attempt_key="stale-client-attempt",
            ),
            user=user,
            session=session,
        )
    assert passed_error.value.error_code == "MASTERY_DRILL_ITEM_ALREADY_PASSED"

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None)))
    background_tasks = BackgroundTasks()
    completion = await exams_api.complete_mastery_drill(
        request=request,
        background_tasks=background_tasks,
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=MasteryDrillCompleteRequest(completion_key="complete-1", duration_seconds=20),
        user=user,
        session=session,
    )
    completion_retry = await exams_api.complete_mastery_drill(
        request=request,
        background_tasks=BackgroundTasks(),
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=MasteryDrillCompleteRequest(completion_key="complete-network-retry", duration_seconds=20),
        user=user,
        session=session,
    )

    session.expire_all()
    paper = session.get(ExamPaper, paper_id)
    drill = exams_repo.get_mastery_drill_session_by_paper(session, paper_id=paper_id)
    item = session.get(ExamPaperItem, item_id)
    attempts = session.exec(
        select(MasteryDrillAttempt).where(MasteryDrillAttempt.mastery_drill_session_id == int(drill.id or 0))
    ).all()
    profile_sync = exams_repo.get_exam_profile_sync(session, paper_id=paper_id)

    assert completion.data.status == completion_retry.data.status == "completed"
    assert paper is not None and paper.status == "graded"
    assert paper.score_obtained == 0.0
    assert paper.total_score == 1.0
    assert drill is not None and drill.status == "completed"
    assert drill.total_attempts == 2
    assert drill.wrong_attempts == 1
    assert item is not None and item.is_correct is True and item.answer_content == "A"
    assert len(attempts) == 2
    assert profile_sync is not None and profile_sync.status == "pending"

    mastery = update_mastery_from_exam(session, paper_id)
    state = session.exec(
        select(app.models.UserKnowledgeState).where(
            app.models.UserKnowledgeState.knowledge_unit_id == int(unit.id or 0)
        )
    ).one()
    assert mastery.states_updated == 1
    assert state.total_attempts == 2
    assert state.correct_attempts == 1

    history = await exams_api.exam_history(
        request=request,
        background_tasks=BackgroundTasks(),
        course_id=COURSE_ID,
        page=1,
        size=20,
        user=user,
        session=session,
    )
    history_item = next(item for item in history.data.items if item.id == paper_id)
    assert history_item.mastery_drill is not None
    assert history_item.mastery_drill.total_attempts == 2
    assert history_item.mastery_drill.wrong_attempts == 1
    assert history_item.mastery_drill.attempt_accuracy == 0.5


@pytest.mark.anyio
async def test_mastery_drill_attempt_runs_and_cleans_up_lease_heartbeat(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)
    heartbeat_started = asyncio.Event()
    heartbeat_cancelled = asyncio.Event()

    async def fake_heartbeat(**_kwargs):
        heartbeat_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            heartbeat_cancelled.set()
            raise

    async def fake_grade(*, answer: str, item: ExamPaperItem, **_kwargs):
        await heartbeat_started.wait()
        return QuestionTemplateGradeResponse(
            question_template_id=int(item.question_template_id or 0),
            question_type=item.question_type,
            is_correct=answer == "A",
            score_obtained=1.0,
            score_max=1.0,
            feedback_text="correct",
            error_cause_label=None,
            grading_mode="objective_rule",
            correct_answer=item.answer_snapshot,
        )

    monkeypatch.setattr(exams_api, "_renew_mastery_drill_attempt_lease_loop", fake_heartbeat)
    monkeypatch.setattr(exams_api, "_grade_exam_paper_item_answer", fake_grade)
    started = await _start(session, user, template)

    response = await exams_api.record_mastery_drill_attempt(
        course_id=COURSE_ID,
        exam_paper_id=int(started.data.id),
        body=MasteryDrillAttemptRequest(
            exam_paper_item_id=int(started.data.items[0].id),
            answer="A",
            attempt_key="heartbeat-attempt",
        ),
        user=user,
        session=session,
    )

    assert response.data.status == "graded"
    assert heartbeat_started.is_set()
    assert heartbeat_cancelled.is_set()


@pytest.mark.anyio
async def test_mastery_drill_attempt_cancellation_releases_claim(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)
    heartbeat_started = asyncio.Event()

    async def fake_heartbeat(**_kwargs):
        heartbeat_started.set()
        await asyncio.Event().wait()

    async def blocking_grade(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(exams_api, "_renew_mastery_drill_attempt_lease_loop", fake_heartbeat)
    monkeypatch.setattr(exams_api, "_grade_exam_paper_item_answer", blocking_grade)
    started = await _start(session, user, template)
    request_task = asyncio.create_task(
        exams_api.record_mastery_drill_attempt(
            course_id=COURSE_ID,
            exam_paper_id=int(started.data.id),
            body=MasteryDrillAttemptRequest(
                exam_paper_item_id=int(started.data.items[0].id),
                answer="A",
                attempt_key="cancelled-attempt",
            ),
            user=user,
            session=session,
        )
    )
    await heartbeat_started.wait()
    request_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await request_task

    session.expire_all()
    attempt = session.exec(
        select(MasteryDrillAttempt).where(MasteryDrillAttempt.attempt_key == "cancelled-attempt")
    ).one()
    assert attempt.status == "failed"
    assert attempt.claim_token == ""
    assert attempt.lease_expires_at is None
    assert attempt.error_code == "MASTERY_DRILL_ATTEMPT_CANCELLED"


@pytest.mark.anyio
async def test_mastery_drill_completion_preserves_partial_first_attempt_score(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)

    async def fake_partial_grade(*, item: ExamPaperItem, **_kwargs):
        return QuestionTemplateGradeResponse(
            question_template_id=int(item.question_template_id or 0),
            question_type=item.question_type,
            is_correct=True,
            score_obtained=0.75,
            score_max=1.0,
            feedback_text="基本正确，但仍有少量遗漏。",
            error_cause_label=None,
            grading_mode="subjective_llm",
            correct_answer=item.answer_snapshot,
        )

    monkeypatch.setattr(exams_api, "_grade_exam_paper_item_answer", fake_partial_grade)
    started = await _start(session, user, template, session_key="partial-score-session")
    paper_id = int(started.data.id)
    item_id = int(started.data.items[0].id)
    attempt = await exams_api.record_mastery_drill_attempt(
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=MasteryDrillAttemptRequest(
            exam_paper_item_id=item_id,
            answer="A",
            attempt_key="partial-first-attempt",
        ),
        user=user,
        session=session,
    )
    assert attempt.data.is_correct is True
    assert attempt.data.score_obtained == pytest.approx(0.75)

    await exams_api.complete_mastery_drill(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
        background_tasks=BackgroundTasks(),
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        body=MasteryDrillCompleteRequest(completion_key="partial-score-complete"),
        user=user,
        session=session,
    )
    session.expire_all()
    paper = session.get(ExamPaper, paper_id)
    assert paper is not None
    assert paper.total_score == pytest.approx(1.0)
    assert paper.score_obtained == pytest.approx(0.75)


@pytest.mark.anyio
async def test_mastery_drill_rejects_completion_until_every_item_is_passed(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)
    started = await _start(session, user, template)

    with pytest.raises(AITeachMeError) as error:
        await exams_api.complete_mastery_drill(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
            background_tasks=BackgroundTasks(),
            course_id=COURSE_ID,
            exam_paper_id=int(started.data.id),
            body=MasteryDrillCompleteRequest(completion_key="too-early"),
            user=user,
            session=session,
        )

    assert error.value.error_code == "MASTERY_DRILL_ITEMS_INCOMPLETE"


@pytest.mark.anyio
async def test_mastery_drill_attempt_key_rejects_changed_payload(
    session: Session,
    user: CurrentUserContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template, _unit = _seed_course_and_template(session)
    monkeypatch.setattr(exams_api, "_capture_exam_event", lambda *_args, **_kwargs: None)

    async def fake_grade(*, answer: str, item: ExamPaperItem, **_kwargs):
        return QuestionTemplateGradeResponse(
            question_template_id=int(item.question_template_id or 0),
            question_type=item.question_type,
            is_correct=False,
            score_obtained=0.0,
            score_max=1.0,
            feedback_text="retry",
            error_cause_label="concept_gap",
            grading_mode="objective_rule",
            correct_answer=item.answer_snapshot,
        )

    monkeypatch.setattr(exams_api, "_grade_exam_paper_item_answer", fake_grade)
    started = await _start(session, user, template)
    item_id = int(started.data.items[0].id)
    await exams_api.record_mastery_drill_attempt(
        course_id=COURSE_ID,
        exam_paper_id=int(started.data.id),
        body=MasteryDrillAttemptRequest(
            exam_paper_item_id=item_id,
            answer="B",
            attempt_key="same-key",
        ),
        user=user,
        session=session,
    )

    with pytest.raises(AITeachMeError) as error:
        await exams_api.record_mastery_drill_attempt(
            course_id=COURSE_ID,
            exam_paper_id=int(started.data.id),
            body=MasteryDrillAttemptRequest(
                exam_paper_item_id=item_id,
                answer="C",
                attempt_key="same-key",
            ),
            user=user,
            session=session,
        )

    assert error.value.error_code == "MASTERY_DRILL_ATTEMPT_CONFLICT"
