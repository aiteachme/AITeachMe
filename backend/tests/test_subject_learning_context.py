from sqlmodel import Session, SQLModel, create_engine, select

from app.models.knowledge_doc import KnowledgeDoc
from app.models.raw_file import RawFile, SubjectFileLink
from app.models.subject import Subject
from app.models.user import User
from app.workflows.support.subjects.learning_context import (
    clear_subject_learning_context,
    load_subject_llm_context,
    update_subject_learning_context_from_docgen,
)


def test_subject_learning_context_published_snapshot_roundtrip():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, Subject.__table__, RawFile.__table__, SubjectFileLink.__table__],
    )

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
        session.add(
            Subject(
                user_id="local",
                slug="math",
                name="Calculus",
                description="Differential calculus study space.",
                user_intent="Prepare for final exam weak points.",
            )
        )
        session.add(
            RawFile(
                id=7,
                uid="file_derivatives",
                user_id="local",
                subject="math",
                filename="derivatives.md",
                filetype="md",
                file_path="uploads/derivatives.md",
                markdown_path="users/local/files/file_derivatives/raw.md",
                markdown_content="# Derivatives",
            )
        )
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
        assert "长期学习意图：Prepare for final exam weak points." in subject.learning_intent_text
        assert "本次构建请求：Focus on exam-ready derivatives." in subject.learning_intent_text
        assert "\n- 文档风格：" in subject.learning_intent_text
        assert subject.document_summary_json["version_no"] == 3
        assert subject.document_summary_json["subject_user_intent"] == "Prepare for final exam weak points."
        assert subject.document_summary_json["confirmed_plan"]["selected_file_ids"] == [7]
        assert subject.document_summary_json["chapters"][0]["source_file_ids"] == [7]
        assert subject.document_summary_json["chapters"][0]["source_raw_file_ids"] == [7]
        assert subject.document_summary_json["chapters"][0]["source_file_uids"] == ["file_derivatives"]
        assert subject.document_summary_json["source_files"][0]["raw_file_id"] == 7
        assert subject.document_summary_json["source_files"][0]["file_uid"] == "file_derivatives"
        assert "Derivatives" in load_subject_llm_context(session, subject="math")

        assert clear_subject_learning_context(session, subject="math") is True
        session.commit()
        session.refresh(subject)

    assert subject.learning_intent_text == ""
    assert subject.subject_intro_text == ""
    assert subject.document_summary_json == {}
    assert subject.llm_context_text == ""
