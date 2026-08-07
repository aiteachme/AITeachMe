from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401 - register every SQLModel table
from app.api import exams as exams_api
from app.models import (
    Course,
    CourseInitialExamJob,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    QuestionKnowledgeUnitLink,
)
from app.repositories import exams_repo
from app.utils.time import utcnow
from app.workflows.examine import initial_exam as initial_exam_service
from app.workflows.examine import prewarm as prewarm_service
from app.workflows.examine.question_build.lib import generator as question_generator
from app.workflows.examine.question_build.lib.generator import ExamQuestionDraft


COURSE_ID = "course_initial_exam"
USER_ID = "user-initial-exam"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(
            Course(
                id=COURSE_ID,
                user_id=USER_ID,
                name="Initial exam course",
                description="Course used to verify one-time automatic exam generation.",
            )
        )
        db.commit()
        yield db


@pytest.fixture
def managed_session(monkeypatch: pytest.MonkeyPatch, session: Session) -> Session:
    @contextmanager
    def _managed_session() -> Iterator[Session]:
        yield session

    monkeypatch.setattr(initial_exam_service, "managed_session", _managed_session)
    monkeypatch.setattr(exams_api, "managed_session", _managed_session)
    return session


@pytest.mark.anyio
async def test_initial_exam_job_runs_once_and_remains_completed_after_paper_deletion(
    monkeypatch: pytest.MonkeyPatch,
    managed_session: Session,
) -> None:
    trigger_count = 0
    applied_model_overrides: list[str | None] = []

    @contextmanager
    def fake_model_override(value: str | None):
        applied_model_overrides.append(value)
        yield None

    async def fake_trigger(**_kwargs) -> prewarm_service.ExamPrewarmTriggerResult:
        nonlocal trigger_count
        trigger_count += 1
        paper = ExamPaper(
            course_id=COURSE_ID,
            user_id=USER_ID,
            exam_mode="web_practice",
            status="ready",
            visibility="visible",
            generation_origin="prewarm",
            total_items=10,
        )
        managed_session.add(paper)
        managed_session.commit()
        managed_session.refresh(paper)
        return prewarm_service.ExamPrewarmTriggerResult(
            status="requested",
            course_id=COURSE_ID,
            user_id=USER_ID,
            exam_mode="web_practice",
            num_questions=10,
            exam_paper_id=int(paper.id or 0),
        )

    monkeypatch.setattr(prewarm_service, "trigger_default_exam_prewarm_for_course", fake_trigger)
    monkeypatch.setattr(initial_exam_service, "use_runtime_model_override", fake_model_override)

    await initial_exam_service.run_course_initial_exam_job(
        course_id=COURSE_ID,
        user_id=USER_ID,
        build_session_id="first-build",
        model_override="light",
    )
    await initial_exam_service.run_course_initial_exam_job(
        course_id=COURSE_ID,
        user_id=USER_ID,
        build_session_id="later-build",
        model_override="reason",
    )

    managed_session.expire_all()
    job = managed_session.exec(
        select(CourseInitialExamJob).where(CourseInitialExamJob.course_id == COURSE_ID)
    ).one()
    assert trigger_count == 1
    assert job.status == "completed"
    assert job.build_session_id == "first-build"
    assert job.model_override == "light"
    assert job.exam_paper_id is not None
    assert applied_model_overrides == ["light"]

    assert exams_repo.delete_exam_paper_cascade(managed_session, paper_id=int(job.exam_paper_id))
    managed_session.expire_all()
    job = managed_session.exec(
        select(CourseInitialExamJob).where(CourseInitialExamJob.course_id == COURSE_ID)
    ).one()
    assert job.status == "completed"
    assert job.exam_paper_id is None

    await initial_exam_service.run_course_initial_exam_job(
        course_id=COURSE_ID,
        user_id=USER_ID,
        build_session_id="third-build",
    )
    assert trigger_count == 1
    assert managed_session.exec(select(ExamPaper)).all() == []


def test_initial_exam_recovery_preserves_model_override(
    monkeypatch: pytest.MonkeyPatch,
    managed_session: Session,
) -> None:
    managed_session.add(
        CourseInitialExamJob(
            course_id=COURSE_ID,
            user_id=USER_ID,
            status="pending",
            build_session_id="recover-build",
            model_override="reason",
            next_attempt_at=utcnow() - timedelta(seconds=1),
        )
    )
    managed_session.commit()
    scheduled: list[dict[str, object]] = []

    def fake_schedule(_registry, **kwargs) -> bool:
        scheduled.append(dict(kwargs))
        return True

    monkeypatch.setattr(initial_exam_service, "schedule_course_initial_exam_job", fake_schedule)

    recovered = initial_exam_service.recover_course_initial_exam_jobs_once(object())

    assert recovered == 1
    assert scheduled == [
        {
            "course_id": COURSE_ID,
            "user_id": USER_ID,
            "build_session_id": "recover-build",
            "model_override": "reason",
        }
    ]


@pytest.mark.anyio
async def test_initial_exam_job_retries_without_leaving_failed_placeholder_papers(
    monkeypatch: pytest.MonkeyPatch,
    managed_session: Session,
) -> None:
    trigger_count = 0

    async def fake_trigger(**_kwargs) -> prewarm_service.ExamPrewarmTriggerResult:
        nonlocal trigger_count
        trigger_count += 1
        paper = ExamPaper(
            course_id=COURSE_ID,
            user_id=USER_ID,
            exam_mode="web_practice",
            status="failed" if trigger_count == 1 else "ready",
            visibility="visible",
            generation_origin="prewarm",
            total_items=10,
        )
        managed_session.add(paper)
        managed_session.commit()
        managed_session.refresh(paper)
        return prewarm_service.ExamPrewarmTriggerResult(
            status="requested",
            course_id=COURSE_ID,
            user_id=USER_ID,
            exam_mode="web_practice",
            num_questions=10,
            exam_paper_id=int(paper.id or 0),
        )

    monkeypatch.setattr(prewarm_service, "trigger_default_exam_prewarm_for_course", fake_trigger)
    monkeypatch.setattr(initial_exam_service, "INITIAL_EXAM_RETRY_DELAY", timedelta(0))

    await initial_exam_service.run_course_initial_exam_job(course_id=COURSE_ID, user_id=USER_ID)
    await initial_exam_service.run_course_initial_exam_job(course_id=COURSE_ID, user_id=USER_ID)

    managed_session.expire_all()
    job = managed_session.exec(select(CourseInitialExamJob)).one()
    papers = managed_session.exec(select(ExamPaper)).all()
    assert trigger_count == 2
    assert job.status == "completed"
    assert job.attempt_count == 2
    assert len(papers) == 1
    assert papers[0].status == "ready"
    assert job.exam_paper_id == papers[0].id


@pytest.mark.anyio
async def test_initial_exam_can_be_generated_from_published_docs_without_knowledge_units(
    monkeypatch: pytest.MonkeyPatch,
    managed_session: Session,
) -> None:
    managed_session.add(
        KnowledgeDocument(
            course_id=COURSE_ID,
            chapter_index=1,
            title="Published chapter",
            markdown_content="# Concepts\n\nThe course source is ready for a quiz.",
            status="published",
            is_current=True,
            version=1,
            version_no=1,
        )
    )
    managed_session.commit()

    stale_paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="generating",
        visibility="visible",
        generation_origin="prewarm",
        total_items=10,
        updated_at=utcnow() - exams_api.EXAM_GENERATION_STALE_AFTER - timedelta(seconds=1),
    )
    managed_session.add(stale_paper)
    managed_session.commit()
    managed_session.refresh(stale_paper)
    stale_paper_id = int(stale_paper.id or 0)
    deleted_paper_ids: list[int] = []
    delete_exam_paper_cascade = exams_repo.delete_exam_paper_cascade

    def track_delete_exam_paper_cascade(session: Session, *, paper_id: int) -> bool:
        deleted_paper_ids.append(paper_id)
        return delete_exam_paper_cascade(session, paper_id=paper_id)

    async def fake_generate_exam_from_text(**kwargs) -> list[ExamQuestionDraft]:
        assert kwargs["num_questions"] == 10
        assert "course source is ready" in kwargs["knowledge_text"]
        return [
            ExamQuestionDraft(
                item_order=order,
                question_type="true_false",
                difficulty="medium",
                stem=f"Statement number {order} is supported by the published source.",
                correct_answer="True",
                explanation="The published source directly supports this statement.",
            )
            for order in range(1, 11)
        ]

    monkeypatch.setattr(question_generator, "generate_exam_from_text", fake_generate_exam_from_text)
    monkeypatch.setattr(
        exams_api,
        "_find_default_auto_prewarm_candidate",
        lambda *_args, **_kwargs: stale_paper,
    )
    monkeypatch.setattr(exams_repo, "delete_exam_paper_cascade", track_delete_exam_paper_cascade)
    monkeypatch.setattr(exams_api, "_publish_exam_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(exams_api, "_capture_exam_generated_event", lambda *_args, **_kwargs: None)

    paper_id = await exams_api._run_initial_exam_from_published_docs_background(
        course_id=COURSE_ID,
        user_id=USER_ID,
    )

    assert paper_id is not None
    paper = managed_session.get(ExamPaper, int(paper_id))
    assert paper is not None
    assert paper.status == "ready"
    assert paper.generation_origin == "prewarm"
    assert paper.total_items == 10
    assert deleted_paper_ids == [stale_paper_id]
    assert len(managed_session.exec(select(ExamPaperItem)).all()) == 10
    assert managed_session.exec(select(QuestionKnowledgeUnitLink)).all() == []
