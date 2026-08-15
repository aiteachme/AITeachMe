from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import deps
from app.api import exams as exams_api
from app.api.deps import CurrentUserContext
from app.models import Course, ExamPaper, ExamPaperItem, QuestionTemplate
from app.repositories import exams_repo
from app.utils.time import utcnow
from app.workflows.examine.exam_grade.lib.grader import ExamItemGradeDecision


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(
        engine,
        tables=[
            QuestionTemplate.__table__,
            ExamPaper.__table__,
            ExamPaperItem.__table__,
        ],
    )
    return engine


def _api_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            Course.__table__,
            QuestionTemplate.__table__,
        ],
    )
    return engine


def test_question_template_marking_is_persisted_on_template() -> None:
    engine = _engine()
    with Session(engine) as session:
        template = QuestionTemplate(
            course_id="course_math00000000",
            question_type="single_choice",
            difficulty="medium",
            stem="Which function is not differentiable at x=0?",
            stem_hash="stem-hash-a",
            answer="|x|",
            explanation="Absolute value has different one-sided derivatives at 0.",
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        updated = exams_repo.set_question_template_mark(
            session,
            course_id="course_math00000000",
            template_id=int(template.id or 0),
            is_marked=True,
        )

        assert updated is not None
        assert updated.is_marked is True
        assert int(template.id or 0) in exams_repo.list_marked_question_template_ids(
            session,
            [int(template.id or 0)],
        )

        wrong_course = exams_repo.set_question_template_mark(
            session,
            course_id="course_other00000000",
            template_id=int(template.id or 0),
            is_marked=False,
        )

        assert wrong_course is None
        persisted = session.get(QuestionTemplate, template.id)
        assert persisted is not None
        assert persisted.is_marked is True


def test_question_template_grade_api_reuses_exam_grade_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _api_engine()
    session = Session(engine, expire_on_commit=False)
    try:
        course = Course(id="course_math00000000", user_id="api-user", name="Calculus")
        template = QuestionTemplate(
            course_id=course.id,
            question_type="fill_blank",
            difficulty="medium",
            stem="The derivative of x^2 is {{blank}}.",
            stem_hash="stem-hash-grade-api",
            answer="2x",
            explanation="Apply the power rule.",
        )
        session.add(course)
        session.add(template)
        session.commit()
        session.refresh(template)

        captured: dict[str, object] = {}

        async def fake_run_exam_grade_workflow(*, course_id: str, course_name: str = "", items: list[ExamPaperItem], progress_callback=None):
            captured["course_id"] = course_id
            captured["course_name"] = course_name
            captured["item"] = items[0]
            return [
                ExamItemGradeDecision(
                    is_correct=True,
                    score_obtained=1.0,
                    score_max=1.0,
                    feedback_text="Power rule is applied correctly.",
                    error_cause_label=None,
                    grading_mode="subjective_llm",
                )
            ]

        monkeypatch.setattr(exams_api, "run_exam_grade_workflow", fake_run_exam_grade_workflow)
        analytics_events: list[tuple[str, dict[str, object]]] = []
        monkeypatch.setattr(
            exams_api,
            "capture_product_event_later",
            lambda event, **kwargs: analytics_events.append((event, kwargs)) or None,
        )

        app = FastAPI()
        app.include_router(exams_api.router)

        def override_get_db():
            yield session

        def override_current_user_context() -> CurrentUserContext:
            return CurrentUserContext(user_id="api-user", email=None, is_local=True)

        app.dependency_overrides[deps.get_db] = override_get_db
        app.dependency_overrides[deps.get_current_user_context] = override_current_user_context

        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/courses/{course.id}/exams/question-templates/{template.id}/grade",
                json={"answer": "2x"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["question_template_id"] == template.id
        assert data["question_type"] == "fill_blank"
        assert data["is_correct"] is True
        assert data["grading_mode"] == "subjective_llm"
        assert data["feedback_text"] == "Power rule is applied correctly."

        graded_item = captured["item"]
        assert isinstance(graded_item, ExamPaperItem)
        assert captured["course_id"] == course.id
        assert captured["course_name"] == "Calculus"
        assert graded_item.question_template_id == template.id
        assert graded_item.question_type == "fill_blank"
        assert graded_item.answer_content == "2x"
        assert graded_item.answer_snapshot == "2x"
        assert analytics_events[0][0] == "question_template_answer_graded"
        analytics_properties = analytics_events[0][1]["properties"]
        assert analytics_properties["question_type"] == "fill_blank"
        assert analytics_properties["grading_mode"] == "subjective_llm"
        assert analytics_properties["score_obtained"] == 1.0
        assert "2x" not in str(analytics_properties)

        with TestClient(app) as client:
            ephemeral_response = client.post(
                f"/api/v1/courses/{course.id}/exams/question-templates/{template.id}/grade",
                json={"answer": "2x", "ephemeral": True},
            )

        assert ephemeral_response.status_code == 200
        assert len(analytics_events) == 1
    finally:
        session.close()


def test_wrong_question_template_ids_filter_visible_user_attempts() -> None:
    engine = _engine()
    with Session(engine) as session:
        target_template = QuestionTemplate(
            course_id="course_math00000000",
            question_type="single_choice",
            difficulty="medium",
            stem="Which function is not differentiable at x=0?",
            stem_hash="stem-hash-wrong-target",
            answer="|x|",
            explanation="Absolute value has different one-sided derivatives at 0.",
        )
        correct_template = QuestionTemplate(
            course_id="course_math00000000",
            question_type="true_false",
            difficulty="easy",
            stem="Every differentiable function is continuous.",
            stem_hash="stem-hash-wrong-correct",
            answer="True",
            explanation="Differentiability implies continuity.",
        )
        session.add(target_template)
        session.add(correct_template)
        session.commit()
        session.refresh(target_template)
        session.refresh(correct_template)

        target_id = int(target_template.id or 0)
        correct_id = int(correct_template.id or 0)
        now = utcnow()

        def add_attempt(
            *,
            template: QuestionTemplate,
            is_correct: bool,
            course_id: str = "course_math00000000",
            user_id: str = "local",
            visibility: str = "visible",
        ) -> None:
            paper = ExamPaper(
                course_id=course_id,
                user_id=user_id,
                exam_mode="web_practice",
                status="graded",
                visibility=visibility,
                total_items=1,
                submitted_at=now,
                graded_at=now,
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
                    answer_content=template.answer if is_correct else "wrong",
                    is_correct=is_correct,
                    score_obtained=1.0 if is_correct else 0.0,
                    score_max=1.0,
                    answered_at=now,
                )
            )
            session.commit()

        add_attempt(template=target_template, is_correct=False)
        add_attempt(template=correct_template, is_correct=True)
        add_attempt(template=correct_template, is_correct=False, user_id="other-user")
        add_attempt(template=correct_template, is_correct=False, course_id="course_other00000000")
        add_attempt(template=correct_template, is_correct=False, visibility="hidden")

        assert exams_repo.list_wrong_question_template_ids(
            session,
            course_id="course_math00000000",
            user_id="local",
            template_ids=[target_id, correct_id],
        ) == {target_id}


def test_question_template_answer_history_filters_visible_user_attempts() -> None:
    engine = _engine()
    with Session(engine) as session:
        template = QuestionTemplate(
            course_id="course_math00000000",
            question_type="single_choice",
            difficulty="medium",
            stem="Which function is not differentiable at x=0?",
            stem_hash="stem-hash-history",
            answer="|x|",
            explanation="Absolute value has different one-sided derivatives at 0.",
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        now = utcnow()

        def add_attempt(
            *,
            course_id: str = "course_math00000000",
            user_id: str = "local",
            visibility: str = "visible",
            answered_offset_minutes: int | None = 0,
            answer_content: str = "|x|",
        ) -> tuple[ExamPaper, ExamPaperItem]:
            paper = ExamPaper(
                course_id=course_id,
                user_id=user_id,
                exam_mode="web_practice",
                status="graded",
                visibility=visibility,
                total_items=1,
                submitted_at=now,
                graded_at=now,
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
                answer_content=answer_content,
                is_correct=answer_content == template.answer,
                score_obtained=1.0 if answer_content == template.answer else 0.0,
                score_max=1.0,
                answered_at=None if answered_offset_minutes is None else now + timedelta(minutes=answered_offset_minutes),
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return paper, item

        _older_paper, older_item = add_attempt(answered_offset_minutes=-5, answer_content="x")
        latest_paper, latest_item = add_attempt(answered_offset_minutes=5, answer_content="|x|")
        add_attempt(user_id="other-user", answered_offset_minutes=10)
        add_attempt(course_id="course_other00000000", answered_offset_minutes=15)
        add_attempt(visibility="hidden", answered_offset_minutes=20)
        add_attempt(answered_offset_minutes=None)

        rows = exams_repo.list_question_template_answer_history(
            session,
            course_id="course_math00000000",
            user_id="local",
            template_id=int(template.id or 0),
            limit=10,
        )

        assert [(paper.id, item.id) for item, paper in rows] == [
            (latest_paper.id, latest_item.id),
            (_older_paper.id, older_item.id),
        ]
        assert rows[0][0].answer_content == "|x|"
        assert rows[1][0].answer_content == "x"

        limited_rows = exams_repo.list_question_template_answer_history(
            session,
            course_id="course_math00000000",
            user_id="local",
            template_id=int(template.id or 0),
            limit=1,
        )

        assert len(limited_rows) == 1
        assert limited_rows[0][0].id == latest_item.id
