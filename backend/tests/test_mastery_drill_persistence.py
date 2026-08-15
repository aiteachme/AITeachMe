from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
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
    QuestionTemplate,
)
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import exams_repo
from app.schemas.exams import (
    ExamGenerateRequest,
    MasteryDrillAttemptRequest,
    MasteryDrillCompleteRequest,
    MasteryDrillPrepareRequest,
    MasteryDrillStartRequest,
)
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow


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


def _assert_ephemeral_only(error: pytest.ExceptionInfo[AITeachMeError]) -> None:
    assert error.value.status_code == 410
    assert error.value.error_code == "MASTERY_DRILL_EPHEMERAL_ONLY"


@pytest.mark.anyio
async def test_durable_mastery_drill_endpoints_are_retired_without_writes(
    session: Session,
    user: CurrentUserContext,
) -> None:
    with pytest.raises(AITeachMeError) as active_error:
        await exams_api.active_mastery_drill(course_id=COURSE_ID, user=user, session=session)
    _assert_ephemeral_only(active_error)

    with pytest.raises(AITeachMeError) as start_error:
        await exams_api.start_mastery_drill(
            course_id=COURSE_ID,
            body=MasteryDrillStartRequest(
                session_key="legacy-start",
                question_template_ids=[1],
                configured_question_count=1,
            ),
            user=user,
            session=session,
        )
    _assert_ephemeral_only(start_error)

    with pytest.raises(AITeachMeError) as attempt_error:
        await exams_api.record_mastery_drill_attempt(
            course_id=COURSE_ID,
            exam_paper_id=1,
            body=MasteryDrillAttemptRequest(
                exam_paper_item_id=1,
                answer="A",
                attempt_key="legacy-attempt",
            ),
            user=user,
            session=session,
        )
    _assert_ephemeral_only(attempt_error)

    with pytest.raises(AITeachMeError) as complete_error:
        await exams_api.complete_mastery_drill(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
            background_tasks=BackgroundTasks(),
            course_id=COURSE_ID,
            exam_paper_id=1,
            body=MasteryDrillCompleteRequest(completion_key="legacy-complete"),
            user=user,
            session=session,
        )
    _assert_ephemeral_only(complete_error)

    assert session.exec(select(ExamPaper)).all() == []
    assert session.exec(select(MasteryDrillSession)).all() == []
    assert session.exec(select(MasteryDrillAttempt)).all() == []


@pytest.mark.anyio
async def test_generic_generation_also_rejects_mastery_drill(
    session: Session,
    user: CurrentUserContext,
) -> None:
    session.add(Course(id=COURSE_ID, user_id=USER_ID, name="Ephemeral Drill"))
    session.commit()

    with pytest.raises(AITeachMeError) as error:
        await exams_api.generate_exam(
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(background_task_registry=None))),
            background_tasks=BackgroundTasks(),
            course_id=COURSE_ID,
            body=ExamGenerateRequest(exam_mode="mastery_drill", num_questions=1),
            user=user,
            session=session,
        )
    _assert_ephemeral_only(error)
    assert session.exec(select(ExamPaper)).all() == []


@pytest.mark.anyio
async def test_prepare_mastery_drill_reuses_sufficient_bank_without_generation(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    user: CurrentUserContext,
) -> None:
    session.add(Course(id=COURSE_ID, user_id=USER_ID, name="Bank-first Drill"))
    session.add_all([
        QuestionTemplate(
            course_id=COURSE_ID,
            question_type="single_choice",
            difficulty="easy",
            stem=f"Existing reusable question {index}?",
            stem_hash=f"existing-reusable-{index}",
            options_json=json.dumps(["A", "B", "C", "D"]),
            answer="A",
            explanation="Existing explanation.",
        )
        for index in range(2)
    ])
    session.commit()

    async def fail_if_generated(**_kwargs):
        raise AssertionError("the question workflow must not run when the bank already satisfies the config")

    monkeypatch.setattr(exams_api, "run_question_build_workflow", fail_if_generated)

    response = await exams_api.prepare_mastery_drill(
        course_id=COURSE_ID,
        body=MasteryDrillPrepareRequest(
            num_questions=2,
            question_types=["single_choice"],
        ),
        user=user,
        session=session,
    )

    assert response.data.requested_count == 2
    assert response.data.available_count == 2
    assert response.data.generated_count == 0
    assert len(response.data.templates) == 2
    assert session.exec(select(ExamPaper)).all() == []


@pytest.mark.anyio
async def test_prepare_mastery_drill_releases_request_transaction_before_lock_wait(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    user: CurrentUserContext,
) -> None:
    session.add(Course(id=COURSE_ID, user_id=USER_ID, name="Lock-safe Drill"))
    session.add(
        QuestionTemplate(
            course_id=COURSE_ID,
            question_type="single_choice",
            difficulty="easy",
            stem="Existing lock-safe reusable question?",
            stem_hash="existing-lock-safe-reusable",
            options_json=json.dumps(["A", "B", "C", "D"]),
            answer="A",
            explanation="Existing explanation.",
        )
    )
    session.commit()
    session.exec(select(Course).where(Course.id == COURSE_ID)).one()
    assert session.in_transaction() is True

    @asynccontextmanager
    async def assert_released_before_lock(
        lock_session: Session,
        *,
        course_id: str,
    ):
        assert lock_session is session
        assert course_id == COURSE_ID
        assert lock_session.in_transaction() is False
        yield

    monkeypatch.setattr(exams_api, "_mastery_drill_backfill_lock", assert_released_before_lock)

    response = await exams_api.prepare_mastery_drill(
        course_id=COURSE_ID,
        body=MasteryDrillPrepareRequest(
            num_questions=1,
            question_types=["single_choice"],
        ),
        user=user,
        session=session,
    )

    assert response.data.generated_count == 0


@pytest.mark.anyio
async def test_prepare_mastery_drill_generates_only_shortage_and_syncs_templates_to_bank(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    user: CurrentUserContext,
) -> None:
    session.add(
        Course(
            id=COURSE_ID,
            user_id=USER_ID,
            name="Generated Drill",
            description="A course used to verify mastery-drill question backfill.",
        )
    )
    unit = KnowledgeUnit(
        course_id=COURSE_ID,
        knowledge_unit_type="concept",
        canonical_name="Core concept",
        normalized_name="core_concept",
        summary="The core concept used by generated questions.",
        status="active",
    )
    existing = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="single_choice",
        difficulty="easy",
        stem="Existing bank question?",
        stem_hash="existing-bank-question",
        options_json=json.dumps(["A", "B", "C", "D"]),
        answer="A",
        explanation="Existing explanation.",
    )
    session.add(unit)
    session.add(existing)
    session.commit()
    session.refresh(unit)

    captured: dict[str, object] = {}

    async def fake_question_build_workflow(**kwargs):
        assert session.in_transaction() is False
        captured.update(kwargs)
        requested_count = int(kwargs["question_count"])
        requested_types = list(kwargs["configured_question_types"])
        generated_questions = []
        blueprints = []
        for order in range(1, requested_count + 1):
            question_type = requested_types[(order - 1) % len(requested_types)]
            generated_questions.append(
                {
                    "item_order": order,
                    "question_type": question_type,
                    "difficulty": "medium",
                    "stem": f"Generated mastery question {order}?",
                    "options": ["A", "B", "C", "D"] if question_type.endswith("choice") else None,
                    "correct_answer": "A" if question_type.endswith("choice") else "True",
                    "explanation": f"Generated explanation {order}.",
                    "knowledge_unit_refs": [
                        {"knowledge_unit_id": int(unit.id or 0), "coverage_weight": 1.0}
                    ],
                }
            )
            blueprints.append(
                {
                    "item_order": order,
                    "question_type": question_type,
                    "difficulty": "medium",
                    "knowledge_unit_ids": [int(unit.id or 0)],
                    "rationale": "Fill the configured mastery-drill bank shortage.",
                }
            )
        payload = {
            "generated_questions": generated_questions,
            "question_blueprints": blueprints,
            "failed_questions": [],
            "error": "",
        }
        return SimpleNamespace(
            failed=False,
            error=None,
            value=payload,
            require_value=lambda: payload,
        )

    monkeypatch.setattr(exams_api, "run_question_build_workflow", fake_question_build_workflow)
    monkeypatch.setattr(exams_api, "load_course_llm_context", lambda *_args, **_kwargs: "course context")

    response = await exams_api.prepare_mastery_drill(
        course_id=COURSE_ID,
        body=MasteryDrillPrepareRequest(
            num_questions=3,
            question_types=["single_choice", "true_false"],
        ),
        user=user,
        session=session,
    )

    assert captured["exam_mode"] == "mastery_drill"
    assert captured["question_count"] == 2
    assert captured["configured_question_types"] == ["true_false", "single_choice"]
    assert response.data.requested_count == 3
    assert response.data.available_count == 3
    assert response.data.generated_count == 2
    assert len(response.data.templates) == 3
    persisted = list(session.exec(select(QuestionTemplate)).all())
    assert len(persisted) == 3
    generated = [template for template in persisted if template.stem.startswith("Generated mastery question")]
    assert len(generated) == 2
    assert all(
        exams_repo.find_knowledge_unit_links_by_template(session, int(template.id or 0))
        == [{"knowledge_unit_id": int(unit.id or 0), "coverage_weight": 1.0}]
        for template in generated
    )
    assert session.exec(select(ExamPaper)).all() == []


@pytest.mark.anyio
async def test_concurrent_mastery_drill_prepare_generates_bank_shortage_once(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    user: CurrentUserContext,
) -> None:
    session.add(Course(id=COURSE_ID, user_id=USER_ID, name="Concurrent Drill"))
    session.commit()
    generation_started = asyncio.Event()
    release_generation = asyncio.Event()
    generation_calls = 0

    async def fake_backfill(
        worker_session: Session,
        *,
        course: Course,
        user_id: str,
        question_count: int,
        question_types: list[str],
    ) -> list[QuestionTemplate]:
        nonlocal generation_calls
        generation_calls += 1
        assert course.id == COURSE_ID
        assert user_id == USER_ID
        assert question_count == 1
        assert question_types == ["single_choice"]
        generation_started.set()
        await release_generation.wait()
        template = QuestionTemplate(
            course_id=COURSE_ID,
            question_type="single_choice",
            difficulty="medium",
            stem="Generated exactly once for concurrent prepare?",
            stem_hash="concurrent-prepare-generated-once",
            options_json=json.dumps(["A", "B", "C", "D"]),
            answer="A",
            explanation="The course-level backfill lock prevents duplicate generation.",
        )
        worker_session.add(template)
        worker_session.commit()
        worker_session.refresh(template)
        return [template]

    monkeypatch.setattr(
        exams_api,
        "_generate_mastery_drill_template_backfill",
        fake_backfill,
    )
    body = MasteryDrillPrepareRequest(
        num_questions=1,
        question_types=["single_choice"],
    )
    first_task = asyncio.create_task(
        exams_api.prepare_mastery_drill(
            course_id=COURSE_ID,
            body=body,
            user=user,
            session=session,
        )
    )
    await generation_started.wait()

    with Session(session.get_bind(), expire_on_commit=False) as second_session:
        second_task = asyncio.create_task(
            exams_api.prepare_mastery_drill(
                course_id=COURSE_ID,
                body=body,
                user=user,
                session=second_session,
            )
        )
        await asyncio.sleep(0.02)
        assert generation_calls == 1
        assert second_task.done() is False

        release_generation.set()
        first_response, second_response = await asyncio.gather(first_task, second_task)

    assert generation_calls == 1
    assert first_response.data.generated_count == 1
    assert second_response.data.generated_count == 0
    assert len(first_response.data.templates) == 1
    assert len(second_response.data.templates) == 1


def test_mastery_drill_backfill_plan_requires_two_types_for_smart_mix() -> None:
    templates = [
        QuestionTemplate(
            course_id=COURSE_ID,
            question_type="single_choice",
            difficulty="easy",
            stem=f"Same-type bank question {index}?",
            stem_hash=f"same-type-{index}",
            answer="A",
            explanation="Explanation.",
        )
        for index in range(3)
    ]

    generation_count, generation_types = exams_api._mastery_drill_backfill_plan(
        templates=templates,
        requested_count=3,
        configured_question_types=[],
    )

    assert generation_count == 1
    assert generation_types == ["multiple_choice"]


def test_legacy_mastery_rows_do_not_enter_history_wrong_questions_or_snapshots(
    session: Session,
) -> None:
    now = utcnow()
    session.add(Course(id=COURSE_ID, user_id=USER_ID, name="Legacy Drill Data"))
    template = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="single_choice",
        difficulty="medium",
        stem="Which answer is correct?",
        stem_hash="ephemeral-drill-template",
        options_json=json.dumps(["A", "B"]),
        answer="A",
        explanation="A is correct.",
    )
    mastery_only_template = QuestionTemplate(
        course_id=COURSE_ID,
        question_type="single_choice",
        difficulty="medium",
        stem="Which legacy mastery answer is correct?",
        stem_hash="legacy-mastery-only-template",
        options_json=json.dumps(["A", "B"]),
        answer="A",
        explanation="A is correct.",
    )
    session.add(template)
    session.add(mastery_only_template)
    session.commit()
    session.refresh(template)
    session.refresh(mastery_only_template)

    regular_paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="web_practice",
        status="graded",
        total_items=1,
        created_at=now,
    )
    mastery_paper = ExamPaper(
        course_id=COURSE_ID,
        user_id=USER_ID,
        exam_mode="mastery_drill",
        status="graded",
        total_items=1,
        created_at=now + timedelta(minutes=1),
    )
    session.add(regular_paper)
    session.add(mastery_paper)
    session.commit()
    session.refresh(regular_paper)
    session.refresh(mastery_paper)

    regular_item = ExamPaperItem(
        exam_paper_id=int(regular_paper.id or 0),
        question_template_id=int(template.id or 0),
        item_order=1,
        stem_snapshot=template.stem,
        options_snapshot_json=template.options_json,
        answer_snapshot=template.answer,
        explanation_snapshot=template.explanation,
        difficulty=template.difficulty,
        question_type=template.question_type,
        answer_content="B",
        is_correct=False,
        answered_at=now,
    )
    mastery_item = ExamPaperItem(
        exam_paper_id=int(mastery_paper.id or 0),
        question_template_id=int(mastery_only_template.id or 0),
        item_order=1,
        stem_snapshot=mastery_only_template.stem,
        options_snapshot_json=mastery_only_template.options_json,
        answer_snapshot=mastery_only_template.answer,
        explanation_snapshot=mastery_only_template.explanation,
        difficulty=mastery_only_template.difficulty,
        question_type=mastery_only_template.question_type,
        answer_content="B",
        is_correct=False,
        answered_at=now + timedelta(minutes=1),
    )
    session.add(regular_item)
    session.add(mastery_item)
    session.commit()

    papers, total = exams_repo.list_exam_papers(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        limit=20,
        offset=0,
    )
    wrong_ids = exams_repo.list_wrong_question_template_ids(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        template_ids=[int(template.id or 0), int(mastery_only_template.id or 0)],
    )
    answer_history = exams_repo.list_question_template_answer_history(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        template_id=int(template.id or 0),
    )
    mastery_answer_history = exams_repo.list_question_template_answer_history(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
        template_id=int(mastery_only_template.id or 0),
    )
    snapshots = exams_repo.list_exam_item_snapshots_by_user(
        session,
        course_id=COURSE_ID,
        user_id=USER_ID,
    )

    assert total == 1
    assert [paper.id for paper in papers] == [regular_paper.id]
    assert wrong_ids == {int(template.id or 0)}
    assert [paper.id for _item, paper in answer_history] == [regular_paper.id]
    assert mastery_answer_history == []
    assert [paper_id for _item, _asked_at, paper_id in snapshots] == [int(regular_paper.id or 0)]


def test_legacy_mastery_tables_remain_available_for_database_compatibility() -> None:
    assert "mastery_drill_session" in SQLModel.metadata.tables
    assert "mastery_drill_attempt" in SQLModel.metadata.tables
