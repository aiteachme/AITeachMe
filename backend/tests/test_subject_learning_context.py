from sqlmodel import Session, SQLModel, create_engine, select

from app.models.knowledge_doc import KnowledgeDoc
from app.models.subject import Subject
from app.models.user import User
from app.workflows.support.subjects.learning_context import (
    clear_subject_learning_context,
    load_subject_llm_context,
    update_subject_learning_context_from_docgen,
)


def test_subject_learning_context_published_snapshot_roundtrip():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine, tables=[User.__table__, Subject.__table__])

    doc = KnowledgeDoc(
        id=11,
        subject="math",
        chapter_index=1,
        title="Derivatives",
        summary="Derivative basics.",
        source_file_ids="[7]",
        word_count=900,
    )

    with Session(engine) as session:
        session.add(User(id="local", username="local"))
        session.add(Subject(user_id="local", slug="math", name="Calculus"))
        session.commit()

        updated = update_subject_learning_context_from_docgen(
            session,
            subject="math",
            document_context={
                "subject_display_name": "Calculus",
                "digest_mode": "systematic",
                "user_prompt": "Focus on exam-ready derivatives.",
            },
            chapter_metadatas=[{"chapter_index": 1, "title": "Derivatives"}],
            chapter_assignments=[{"source_file_ids": [7]}],
            knowledge_docs=[doc],
            docgen_artifacts={
                "confirmed_plan": {
                    "selected_file_ids": [7],
                    "chapter_plan": [{"chapter_index": 1, "title": "Derivatives"}],
                },
                "build_metadata": {"confirmed_plan_id": "plan-1"},
            },
            version_no=3,
            build_session_id="build-1",
        )
        session.commit()

        assert updated is not None
        subject = session.exec(select(Subject).where(Subject.slug == "math")).one()
        assert subject.document_summary_json["version_no"] == 3
        assert subject.document_summary_json["confirmed_plan"]["selected_file_ids"] == [7]
        assert subject.document_summary_json["chapters"][0]["source_file_ids"] == [7]
        assert "Derivatives" in load_subject_llm_context(session, subject="math")

        assert clear_subject_learning_context(session, subject="math") is True
        session.commit()
        session.refresh(subject)

    assert subject.learning_intent_text == ""
    assert subject.subject_intro_text == ""
    assert subject.document_summary_json == {}
    assert subject.llm_context_text == ""
