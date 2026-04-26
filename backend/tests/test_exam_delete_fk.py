from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeUnit, QuestionTemplate, UserKnowledgeState
from app.repositories import exams_repo


def test_delete_exam_paper_cascade_clears_profile_source_fk() -> None:
    engine = create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        unit = KnowledgeUnit(
            subject="subj_demo",
            knowledge_unit_type="concept",
            canonical_name="Unit",
            normalized_name="unit",
        )
        session.add(unit)
        session.flush()

        template = QuestionTemplate(
            subject="subj_demo",
            knowledge_unit_id=unit.id,
            question_type="short_answer",
            difficulty="easy",
            stem="Question",
            stem_hash="question-hash",
            answer="Answer",
            explanation="Explanation",
        )
        paper = ExamPaper(subject="subj_demo", user_id="user_a", exam_mode="practice", total_items=1)
        session.add_all([template, paper])
        session.flush()

        session.add(
            ExamPaperItem(
                exam_paper_id=paper.id,
                question_template_id=template.id,
                item_order=1,
                stem_snapshot="Question",
                answer_snapshot="Answer",
                explanation_snapshot="Explanation",
                knowledge_unit_id=unit.id,
                difficulty="easy",
                question_type="short_answer",
            )
        )
        state = UserKnowledgeState(
            user_id="user_a",
            subject="subj_demo",
            knowledge_unit_id=unit.id,
            source_exam_paper_id=paper.id,
        )
        session.add(state)
        session.commit()

        assert exams_repo.delete_exam_paper_cascade(session, paper_id=paper.id) is True

        stored_state = session.get(UserKnowledgeState, state.id)
        assert stored_state is not None
        assert stored_state.source_exam_paper_id is None
        assert session.exec(select(ExamPaper)).all() == []
        assert session.exec(select(ExamPaperItem)).all() == []
