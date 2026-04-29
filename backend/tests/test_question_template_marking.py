from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.models import QuestionTemplate
from app.repositories import exams_repo


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[QuestionTemplate.__table__])
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
