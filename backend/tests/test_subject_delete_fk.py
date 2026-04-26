from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import Session, SQLModel, create_engine, func, select

from app.models import (
    ExamPaper,
    ExamPaperItem,
    KnowledgeUnit,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    QuestionTypeRegistry,
    Subject,
    User,
    UserKnowledgeState,
)
from app.workflows.support.subjects.lib import deletion


def test_delete_subject_removes_exam_fk_dependents_before_papers(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(deletion, "_clear_subject_vector_index_best_effort", lambda _subject: None)
    monkeypatch.setattr(deletion, "_delete_subject_artifacts_best_effort", lambda _subject, user_id=None: None)

    with Session(engine) as session:
        session.add(User(id="user_a", username="user_a"))
        session.commit()

        subject = Subject(user_id="user_a", slug="subj_demo", name="Demo")
        session.add(subject)
        session.flush()

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
            question_type="short_answer",
            difficulty="easy",
            stem="Question",
            stem_hash="question-hash",
            answer="Answer",
            explanation="Explanation",
        )
        paper_a = ExamPaper(subject="subj_demo", user_id="user_a", exam_mode="practice", total_items=1)
        paper_b = ExamPaper(subject="subj_demo", user_id="user_a", exam_mode="practice", total_items=0)
        registry = QuestionTypeRegistry(type_key="short_answer", display_name="Short answer", subject="subj_demo")
        session.add_all([template, paper_a, paper_b, registry])
        session.flush()

        item = ExamPaperItem(
            exam_paper_id=paper_a.id,
            question_template_id=template.id,
            item_order=1,
            stem_snapshot="Question",
            answer_snapshot="Answer",
            explanation_snapshot="Explanation",
            difficulty="easy",
            question_type="short_answer",
        )
        session.add(item)
        session.flush()
        session.add(
            QuestionKnowledgeUnitLink(
                question_template_id=template.id,
                knowledge_unit_id=unit.id,
            )
        )
        session.add(
            QuestionKnowledgeUnitLink(
                exam_paper_item_id=item.id,
                knowledge_unit_id=unit.id,
            )
        )
        session.add(
            UserKnowledgeState(
                user_id="user_a",
                subject="subj_demo",
                knowledge_unit_id=unit.id,
                source_exam_paper_id=paper_a.id,
            )
        )
        session.commit()

        deleted_counts = deletion.delete_subject_with_all_content(session, subject=subject)

        assert deleted_counts["exam_paper"] == 2
        assert deleted_counts["exam_paper_item"] == 1
        assert deleted_counts["user_knowledge_state"] == 1
        assert _count(session, Subject) == 0
        assert _count(session, ExamPaper) == 0
        assert _count(session, ExamPaperItem) == 0
        assert _count(session, QuestionKnowledgeUnitLink) == 0
        assert _count(session, UserKnowledgeState) == 0


def _count(session: Session, model: type) -> int:
    return int(session.exec(select(func.count()).select_from(model)).one())
