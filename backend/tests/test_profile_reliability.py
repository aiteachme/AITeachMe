from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import exams as exams_api
from app.api import profile as profile_api
from app.api.deps import CurrentUserContext
import app.models  # noqa: F401 - register SQLModel tables
from app.repositories import exams_repo, profile_repo
from app.shared.infra.workflow.result import ok_result
from app.models import (
    Course,
    ExamPaper,
    ExamPaperItem,
    ExamProfileSync,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    User,
    UserKnowledgeState,
)
from app.models.knowledge_unit import KnowledgeUnit
from app.utils.time import utcnow
from app.workflows.examine.exam_grade.lib.grader import ExamItemGradeDecision
from app.workflows.interact.chat.lib import retrieval as chat_retrieval
from app.workflows.profile.common.lib import locking as profile_locking
from app.workflows.profile.common.lib.mastery import update_mastery_from_exam
from app.workflows.profile.common.nodes import context as profile_context_nodes
from app.workflows.profile.update import graph as profile_update_graph
from app.workflows.profile import sync as profile_sync_service
from app.workflows.support.courses.lib import deletion as course_deletion


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


@pytest.fixture
def managed_profile_sync_session(monkeypatch: pytest.MonkeyPatch, session: Session) -> Session:
    @contextmanager
    def _managed_session() -> Iterator[Session]:
        try:
            session.expire_all()
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    monkeypatch.setattr(profile_sync_service, "managed_session", _managed_session)
    return session


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


def test_update_mastery_uses_partial_credit_ratio(session: Session) -> None:
    paper, item, unit = _seed_graded_paper(session)
    item.is_correct = False
    item.score_obtained = 0.5
    item.score_max = 1.0
    session.add(item)
    session.commit()

    result = update_mastery_from_exam(session, int(paper.id or 0))
    state = session.get(UserKnowledgeState, result.updated_state_ids[0])

    assert state is not None
    assert state.knowledge_unit_id == unit.id
    assert state.mastery_score == pytest.approx(0.5)
    assert state.total_attempts == 1
    assert state.correct_attempts == 0


def test_compare_and_set_knowledge_state_rejects_stale_version(session: Session) -> None:
    _seed_user_course(session)
    unit, _template = _seed_template(session)
    initial = UserKnowledgeState(
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=int(unit.id or 0),
        total_attempts=1,
        correct_attempts=1,
        state_version=1,
    )
    session.add(initial)
    session.commit()

    current = UserKnowledgeState(
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=int(unit.id or 0),
        total_attempts=2,
        correct_attempts=2,
        state_version=2,
    )
    persisted = profile_repo.compare_and_set_knowledge_state(
        session,
        current,
        expected_state_version=1,
    )
    assert persisted is not None
    assert persisted.total_attempts == 2

    stale = UserKnowledgeState(
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=int(unit.id or 0),
        total_attempts=99,
        correct_attempts=99,
        state_version=2,
    )
    rejected = profile_repo.compare_and_set_knowledge_state(
        session,
        stale,
        expected_state_version=1,
    )
    assert rejected is None

    stored = profile_repo.get_knowledge_state(
        session,
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=int(unit.id or 0),
    )
    assert stored is not None
    assert stored.total_attempts == 2
    assert stored.correct_attempts == 2
    assert stored.state_version == 2


def test_profile_user_lock_key_is_stable_and_user_scoped() -> None:
    first = profile_locking.profile_user_lock_key(USER_ID)
    repeated = profile_locking.profile_user_lock_key(USER_ID)
    another_user = profile_locking.profile_user_lock_key(f"{USER_ID}-other")

    assert first == repeated
    assert first != another_user
    assert -(2**63) <= first < 2**63


def test_postgres_profile_user_lock_executes_transaction_advisory_sql() -> None:
    statements: list[object] = []

    class PostgresSession:
        @staticmethod
        def get_bind():
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        @staticmethod
        def exec(statement):
            statements.append(statement)

    profile_locking.acquire_profile_user_lock(PostgresSession(), user_id=USER_ID)

    assert len(statements) == 1
    compiled = " ".join(
        str(
            statements[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )

    assert compiled == (
        "SELECT pg_advisory_xact_lock"
        f"({profile_locking.profile_user_lock_key(USER_ID)}) AS pg_advisory_xact_lock_1"
    )


def test_sqlite_profile_write_transaction_restarts_pure_read_as_immediate(
    session: Session,
) -> None:
    statements: list[str] = []
    engine = session.get_bind()

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(str(statement))

    sa.event.listen(engine, "before_cursor_execute", record_statement)
    try:
        session.get(User, "missing-user")
        assert session.in_transaction()

        profile_locking.prepare_profile_write_transaction(session)
    finally:
        sa.event.remove(engine, "before_cursor_execute", record_statement)

    assert session.in_transaction()
    assert "BEGIN IMMEDIATE" in statements


def test_sqlite_profile_write_transaction_rejects_pending_writes(session: Session) -> None:
    session.add(User(id="pending-profile-user", username="pending-profile-user"))

    with pytest.raises(RuntimeError, match="profile_sqlite_transaction_has_pending_writes"):
        profile_locking.prepare_profile_write_transaction(session)


def test_sqlite_profile_write_transaction_does_not_rollback_flushed_writes(
    session: Session,
) -> None:
    user = User(id="flushed-profile-user", username="flushed-profile-user")
    session.add(user)
    session.flush()
    assert not session.new
    assert not session.dirty
    assert not session.deleted

    with pytest.raises(RuntimeError, match="profile_sqlite_transaction_is_not_read_only"):
        profile_locking.prepare_profile_write_transaction(session)

    assert session.get(User, user.id) is user


def test_resolve_profile_context_prepares_loads_locks_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    paper = SimpleNamespace(id=42, course_id=COURSE_ID, user_id=USER_ID)

    class RecordingSession:
        @staticmethod
        def get(model, record_id):
            assert model is ExamPaper
            assert record_id == 42
            events.append("load_paper")
            return paper

        @staticmethod
        def expire_all() -> None:
            events.append("expire_all")

    recording_session = RecordingSession()

    def fake_prepare(actual_session) -> None:
        assert actual_session is recording_session
        events.append("prepare")

    def fake_acquire(actual_session, *, user_id: str) -> None:
        assert actual_session is recording_session
        assert user_id == USER_ID
        events.append("lock_user")

    monkeypatch.setattr(profile_context_nodes, "prepare_profile_write_transaction", fake_prepare)
    monkeypatch.setattr(profile_context_nodes, "acquire_profile_user_lock", fake_acquire)

    node = profile_context_nodes.build_resolve_exam_profile_context_node(session=recording_session)
    result = node(
        {
            "exam_paper_id": 42,
            "course_id": "",
            "user_id": "",
        }
    )

    assert result["course_id"] == COURSE_ID
    assert result["user_id"] == USER_ID
    assert result["error"] is None
    assert events == ["prepare", "load_paper", "lock_user", "expire_all", "load_paper"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("workflow_error", "expected_commit", "expected_rollback"),
    [(None, 1, 0), ("schedule_reviews_failed:test", 0, 1)],
)
async def test_profile_update_owned_session_commits_only_complete_workflow(
    monkeypatch: pytest.MonkeyPatch,
    workflow_error: str | None,
    expected_commit: int,
    expected_rollback: int,
) -> None:
    events: list[str] = []

    class RecordingSession:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0
            self.closes = 0

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

        def close(self) -> None:
            self.closes += 1

    recording_session = RecordingSession()

    async def fake_run_state_graph(**_kwargs):
        events.append("graph")
        return ok_result({"error": workflow_error})

    monkeypatch.setattr(profile_update_graph, "get_session", lambda: recording_session)
    monkeypatch.setattr(profile_update_graph, "run_state_graph", fake_run_state_graph)

    result = await profile_update_graph.run_profile_update_workflow(exam_paper_id=1)

    assert result.ok
    assert recording_session.commits == expected_commit
    assert recording_session.rollbacks == expected_rollback
    assert recording_session.closes == 1
    assert events == ["graph"]


@pytest.mark.anyio
async def test_profile_update_external_session_leaves_lock_transaction_to_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class ExternalSession:
        commits = 0
        rollbacks = 0
        closes = 0

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

        def close(self) -> None:
            self.closes += 1

    external_session = ExternalSession()

    async def fake_run_state_graph(**_kwargs):
        assert _kwargs["graph_builder"]
        events.append("graph")
        return ok_result({"error": None})

    monkeypatch.setattr(profile_update_graph, "run_state_graph", fake_run_state_graph)

    result = await profile_update_graph.run_profile_update_workflow(
        exam_paper_id=7,
        session=external_session,
    )

    assert result.ok
    assert events == ["graph"]
    assert external_session.commits == 0
    assert external_session.rollbacks == 0
    assert external_session.closes == 0


@pytest.mark.anyio
async def test_grade_exam_records_profile_update_failure_without_blocking(
    session: Session,
    managed_profile_sync_session: Session,
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
    monkeypatch.setattr(profile_sync_service, "run_profile_update_workflow", fake_profile_update_workflow)

    response = await exams_api._grade_exam(session, paper)
    assert response.profile_sync is not None
    assert response.profile_sync.status == "pending"
    await profile_sync_service.run_exam_profile_sync_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=int(paper.id or 0),
    )
    session.expire_all()
    profile_sync = session.exec(
        sa.select(ExamProfileSync).where(ExamProfileSync.exam_paper_id == int(paper.id or 0))
    ).scalar_one()

    assert response.status == "completed"
    assert response.mastery_consumed is False
    assert profile_sync.status == "retry_wait"
    assert profile_sync.attempt_count == 1
    assert profile_sync.states_updated == 0
    assert profile_sync.review_task_count == 0
    assert profile_sync.last_error_code == "update_mastery_failed"
    assert "secret-provider-token" not in json.dumps(profile_sync.model_dump(), default=str)


@pytest.mark.anyio
async def test_grade_exam_records_profile_update_exception_without_blocking(
    session: Session,
    managed_profile_sync_session: Session,
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
    monkeypatch.setattr(profile_sync_service, "run_profile_update_workflow", fake_profile_update_workflow)

    response = await exams_api._grade_exam(session, paper)
    await profile_sync_service.run_exam_profile_sync_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=int(paper.id or 0),
    )
    session.expire_all()
    profile_sync = session.exec(
        sa.select(ExamProfileSync).where(ExamProfileSync.exam_paper_id == int(paper.id or 0))
    ).scalar_one()

    assert response.status == "completed"
    assert response.mastery_consumed is False
    assert profile_sync.status == "retry_wait"
    assert profile_sync.attempt_count == 1
    assert profile_sync.last_error_code == "RuntimeError"
    assert "secret-provider-token" not in json.dumps(profile_sync.model_dump(), default=str)


@pytest.mark.anyio
async def test_exam_profile_sync_stops_automatic_retry_after_max_attempts(
    session: Session,
    managed_profile_sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper, _item, _unit = _seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    task = exams_repo.ensure_exam_profile_sync(session, paper=paper, auto_commit=True)
    task.attempt_count = profile_sync_service.PROFILE_SYNC_MAX_ATTEMPTS - 1
    session.add(task)
    session.commit()

    async def fake_profile_update_workflow(**_kwargs):
        raise RuntimeError("provider-secret-must-not-leak")

    monkeypatch.setattr(profile_sync_service, "run_profile_update_workflow", fake_profile_update_workflow)
    await profile_sync_service.run_exam_profile_sync_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=paper_id,
    )
    session.expire_all()
    task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id) or task

    assert task.status == "failed"
    assert task.attempt_count == profile_sync_service.PROFILE_SYNC_MAX_ATTEMPTS
    assert task.next_attempt_at is None
    assert task.last_error_code == "RuntimeError"
    assert "provider-secret" not in json.dumps(task.model_dump(), default=str)


def test_exam_profile_sync_claim_lease_and_fencing(session: Session) -> None:
    paper, _item, _unit = _seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    task = exams_repo.ensure_exam_profile_sync(
        session,
        paper=paper,
        next_attempt_at=utcnow(),
        auto_commit=True,
    )
    now = utcnow()

    assert exams_repo.claim_exam_profile_sync(
        session,
        paper_id=paper_id,
        claim_token="first-worker",
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=10),
    )
    renewed_until = now + timedelta(minutes=20)
    assert exams_repo.renew_exam_profile_sync_lease(
        session,
        paper_id=paper_id,
        claim_token="first-worker",
        lease_expires_at=renewed_until,
    )
    assert not exams_repo.claim_exam_profile_sync(
        session,
        paper_id=paper_id,
        claim_token="second-worker",
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=10),
    )

    session.expire_all()
    task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id) or task
    task.lease_expires_at = now - timedelta(seconds=1)
    session.add(task)
    session.commit()

    assert exams_repo.claim_exam_profile_sync(
        session,
        paper_id=paper_id,
        claim_token="second-worker",
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=10),
    )
    assert not exams_repo.finalize_exam_profile_sync(
        session,
        paper_id=paper_id,
        claim_token="first-worker",
        states_updated=99,
        review_task_count=99,
        completed_at=now,
    )
    assert exams_repo.finalize_exam_profile_sync(
        session,
        paper_id=paper_id,
        claim_token="second-worker",
        states_updated=1,
        review_task_count=2,
        completed_at=now,
    )
    session.commit()
    session.expire_all()
    task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id) or task

    assert task.status == "completed"
    assert task.attempt_count == 2
    assert task.states_updated == 1
    assert task.review_task_count == 2


@pytest.mark.anyio
async def test_exam_profile_sync_runs_and_cleans_up_lease_heartbeat(
    session: Session,
    managed_profile_sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper, _item, _unit = _seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    exams_repo.ensure_exam_profile_sync(session, paper=paper, auto_commit=True)
    heartbeat_started = asyncio.Event()
    heartbeat_cancelled = asyncio.Event()

    async def fake_heartbeat(**_kwargs):
        heartbeat_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            heartbeat_cancelled.set()
            raise

    async def fake_profile_update_workflow(**_kwargs):
        await heartbeat_started.wait()
        return ok_result(
            {
                "error": None,
                "mastery_result": {"states_updated": 0},
                "review_task_ids": [],
            }
        )

    monkeypatch.setattr(profile_sync_service, "_renew_exam_profile_sync_lease_loop", fake_heartbeat)
    monkeypatch.setattr(profile_sync_service, "run_profile_update_workflow", fake_profile_update_workflow)

    await profile_sync_service.run_exam_profile_sync_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=paper_id,
    )
    session.expire_all()
    task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id)

    assert task is not None and task.status == "completed"
    assert heartbeat_started.is_set()
    assert heartbeat_cancelled.is_set()


@pytest.mark.anyio
async def test_exam_profile_sync_commits_profile_writes_with_completion(
    session: Session,
    managed_profile_sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper, _item, unit = _seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    exams_repo.ensure_exam_profile_sync(session, paper=paper, auto_commit=True)

    async def fake_profile_update_workflow(**kwargs):
        workflow_session = kwargs["session"]
        workflow_session.add(
            UserKnowledgeState(
                user_id=USER_ID,
                course_id=COURSE_ID,
                knowledge_unit_id=int(unit.id or 0),
                total_attempts=1,
                correct_attempts=1,
                source_exam_paper_id=paper_id,
            )
        )
        return ok_result(
            {
                "error": None,
                "mastery_result": {"states_updated": 1},
                "review_task_ids": [11, 12],
            }
        )

    monkeypatch.setattr(profile_sync_service, "run_profile_update_workflow", fake_profile_update_workflow)

    await profile_sync_service.run_exam_profile_sync_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=paper_id,
    )
    session.expire_all()
    task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id)
    state = profile_repo.get_knowledge_state(
        session,
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=int(unit.id or 0),
    )

    assert task is not None and task.status == "completed"
    assert task.states_updated == 1
    assert task.review_task_count == 2
    assert state is not None and state.total_attempts == 1


@pytest.mark.anyio
async def test_exam_profile_sync_rolls_back_profile_writes_when_completion_fence_is_lost(
    session: Session,
    managed_profile_sync_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper, _item, unit = _seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    exams_repo.ensure_exam_profile_sync(session, paper=paper, auto_commit=True)

    async def fake_profile_update_workflow(**kwargs):
        kwargs["session"].add(
            UserKnowledgeState(
                user_id=USER_ID,
                course_id=COURSE_ID,
                knowledge_unit_id=int(unit.id or 0),
                total_attempts=1,
                correct_attempts=1,
                source_exam_paper_id=paper_id,
            )
        )
        return ok_result(
            {
                "error": None,
                "mastery_result": {"states_updated": 1},
                "review_task_ids": [],
            }
        )

    monkeypatch.setattr(profile_sync_service, "run_profile_update_workflow", fake_profile_update_workflow)
    monkeypatch.setattr(exams_repo, "finalize_exam_profile_sync", lambda *_args, **_kwargs: False)

    await profile_sync_service.run_exam_profile_sync_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
        paper_id=paper_id,
    )
    session.expire_all()
    task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id)
    state = profile_repo.get_knowledge_state(
        session,
        user_id=USER_ID,
        course_id=COURSE_ID,
        knowledge_unit_id=int(unit.id or 0),
    )

    assert task is not None and task.status == "retry_wait"
    assert task.last_error_code == "profile_sync_claim_lost"
    assert state is None


@pytest.mark.anyio
async def test_retry_exam_profile_sync_resets_failed_task_and_schedules_worker(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper, _item, _unit = _seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    task = exams_repo.ensure_exam_profile_sync(
        session,
        paper=paper,
        status="failed",
        auto_commit=True,
    )
    task.attempt_count = profile_sync_service.PROFILE_SYNC_MAX_ATTEMPTS
    task.last_error_code = "update_mastery_failed"
    session.add(task)
    session.commit()

    class Registry:
        def __init__(self) -> None:
            self.names: list[str] = []

        def spawn(self, coro, **kwargs):
            self.names.append(str(kwargs.get("name") or ""))
            coro.close()
            return SimpleNamespace()

    registry = Registry()
    response = await exams_api.retry_exam_profile_sync(
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=registry))),
        background_tasks=BackgroundTasks(),
        course_id=COURSE_ID,
        exam_paper_id=paper_id,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=session,
    )
    session.expire_all()
    task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id) or task

    assert response.data is not None
    assert response.data.status == "pending"
    assert response.data.manual_retry_count == 1
    assert task.status == "pending"
    assert task.attempt_count == profile_sync_service.PROFILE_SYNC_MAX_ATTEMPTS
    assert task.last_error_code == ""
    assert len(registry.names) == 1


def test_exam_profile_sync_recovery_schedules_due_and_expired_tasks(
    session: Session,
    managed_profile_sync_session: Session,
) -> None:
    _seed_user_course(session)
    now = utcnow()
    tasks: list[ExamProfileSync] = []
    for index, (status, next_attempt_at, lease_expires_at) in enumerate(
        [
            ("pending", now - timedelta(seconds=1), None),
            ("retry_wait", now + timedelta(hours=1), None),
            ("processing", None, now - timedelta(seconds=1)),
        ],
        start=1,
    ):
        paper = ExamPaper(
            course_id=COURSE_ID,
            user_id=USER_ID,
            exam_mode="web_practice",
            status="graded",
            total_items=0,
        )
        session.add(paper)
        session.commit()
        session.refresh(paper)
        task = ExamProfileSync(
            exam_paper_id=int(paper.id or 0),
            course_id=COURSE_ID,
            user_id=USER_ID,
            status=status,
            next_attempt_at=next_attempt_at,
            claim_token=f"worker-{index}" if status == "processing" else "",
            lease_expires_at=lease_expires_at,
        )
        session.add(task)
        session.commit()
        tasks.append(task)

    class Registry:
        def __init__(self) -> None:
            self.names: list[str] = []

        def spawn(self, coro, **kwargs):
            self.names.append(str(kwargs.get("name") or ""))
            coro.close()
            return SimpleNamespace()

    registry = Registry()
    scheduled = profile_sync_service.recover_exam_profile_sync_tasks_once(registry)

    assert scheduled == 2
    assert {name.rsplit(":", 1)[-1] for name in registry.names} == {
        str(tasks[0].exam_paper_id),
        str(tasks[2].exam_paper_id),
    }


def test_course_exam_cleanup_deletes_profile_sync_before_paper(session: Session) -> None:
    paper, _item, _unit = _seed_graded_paper(session)
    paper_id = int(paper.id or 0)
    exams_repo.ensure_exam_profile_sync(session, paper=paper, auto_commit=True)

    course_deletion._delete_exam_records(session, course_id=COURSE_ID)
    session.commit()
    session.expire_all()

    assert exams_repo.get_exam_profile_sync(session, paper_id=paper_id) is None
    assert exams_repo.get_exam_paper_by_id(session, paper_id) is None


def test_complete_review_uses_shared_lock_before_profile_business_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    task = SimpleNamespace(knowledge_unit_id=None)

    class RecordingSession:
        @staticmethod
        def expire_all() -> None:
            events.append("expire_all")

    recording_session = RecordingSession()

    def fake_prepare(actual_session) -> None:
        assert actual_session is recording_session
        events.append("prepare")

    def fake_acquire(actual_session, *, user_id: str) -> None:
        assert actual_session is recording_session
        assert user_id == USER_ID
        events.append("lock_user")

    def fake_ensure_course(actual_session, course_id: str, user_id: str):
        assert actual_session is recording_session
        assert course_id == COURSE_ID
        assert user_id == USER_ID
        events.append("ensure_course")
        return SimpleNamespace(id=COURSE_ID)

    def fake_complete(actual_session, **kwargs):
        assert actual_session is recording_session
        assert kwargs == {
            "task_id": 7,
            "user_id": USER_ID,
            "course_id": COURSE_ID,
            "auto_commit": False,
        }
        events.append("complete_review")
        return task

    monkeypatch.setattr(profile_api, "prepare_profile_write_transaction", fake_prepare)
    monkeypatch.setattr(profile_api, "acquire_profile_user_lock", fake_acquire)
    monkeypatch.setattr(profile_api, "_ensure_course", fake_ensure_course)
    monkeypatch.setattr(profile_api.profile_repo, "complete_review_task", fake_complete)
    monkeypatch.setattr(
        profile_api,
        "refresh_course_profile_summary",
        lambda *_args, **_kwargs: events.append("refresh_course_profile"),
    )
    monkeypatch.setattr(
        profile_api,
        "refresh_user_profile_summary",
        lambda *_args, **_kwargs: events.append("refresh_user_profile"),
    )
    monkeypatch.setattr(profile_api, "_review_response", lambda *_args: "completed")

    response = profile_api.complete_review(
        course_id=COURSE_ID,
        task_id=7,
        user=CurrentUserContext(user_id=USER_ID, email=None, is_local=True),
        session=recording_session,
    )

    assert response.data == "completed"
    assert events == [
        "prepare",
        "lock_user",
        "expire_all",
        "ensure_course",
        "complete_review",
        "refresh_course_profile",
        "refresh_user_profile",
    ]


def test_complete_review_refreshes_persisted_profiles(session: Session) -> None:
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

    response = profile_api.complete_review(
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
