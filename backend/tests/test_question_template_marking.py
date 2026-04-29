from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.models import ExamPaper, ExamPaperItem, QuestionTemplate
from app.repositories import exams_repo
from app.utils.time import utcnow


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


def test_question_template_marking_is_persisted_on_template() -> None:
    engine = _engine()
    with Session(engine) as session:
        template = QuestionTemplate(
            subject_id="subj_math00000000",
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
            subject_id="subj_math00000000",
            template_id=int(template.id or 0),
            is_marked=True,
        )

        assert updated is not None
        assert updated.is_marked is True
        assert int(template.id or 0) in exams_repo.list_marked_question_template_ids(
            session,
            [int(template.id or 0)],
        )

        wrong_subject = exams_repo.set_question_template_mark(
            session,
            subject_id="subj_other00000000",
            template_id=int(template.id or 0),
            is_marked=False,
        )

        assert wrong_subject is None
        persisted = session.get(QuestionTemplate, template.id)
        assert persisted is not None
        assert persisted.is_marked is True


def test_question_template_answer_history_filters_visible_user_attempts() -> None:
    engine = _engine()
    with Session(engine) as session:
        template = QuestionTemplate(
            subject_id="subj_math00000000",
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
            subject_id: str = "subj_math00000000",
            user_id: str = "local",
            visibility: str = "visible",
            answered_offset_minutes: int | None = 0,
            answer_content: str = "|x|",
        ) -> tuple[ExamPaper, ExamPaperItem]:
            paper = ExamPaper(
                subject_id=subject_id,
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
        add_attempt(subject_id="subj_other00000000", answered_offset_minutes=15)
        add_attempt(visibility="hidden", answered_offset_minutes=20)
        add_attempt(answered_offset_minutes=None)

        rows = exams_repo.list_question_template_answer_history(
            session,
            subject_id="subj_math00000000",
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
            subject_id="subj_math00000000",
            user_id="local",
            template_id=int(template.id or 0),
            limit=1,
        )

        assert len(limited_rows) == 1
        assert limited_rows[0][0].id == latest_item.id
