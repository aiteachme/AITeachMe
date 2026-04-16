from __future__ import annotations

from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.shared.infra.exceptions import KnowledgeClearConflictError
from app.models import (
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeUnit,
    QuestionTemplate,
    Subject,
    User,
)
from app.workflows.digest.application.knowledge_docs.cleanup_service import clear_subject_knowledge
from app.workflows.support.subjects import delete_subject_record


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, connection_record) -> None:
        del connection_record
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _seed_subject_knowledge(session: Session, *, subject_id: str) -> Subject:
    session.add(User(id="local", username="local"))
    session.commit()

    subject = Subject(user_id="local", slug=subject_id, name="线性代数")
    session.add(subject)

    node_a = KnowledgeUnit(
        subject=subject_id,
        knowledge_unit_type="concept",
        canonical_name="方程",
        normalized_name="方程",
        status="active",
        build_revision_no=1,
    )
    session.add(node_a)
    session.flush()

    node_b = KnowledgeUnit(
        subject=subject_id,
        knowledge_unit_type="concept",
        canonical_name="一次方程",
        normalized_name="一次方程",
        merged_into_knowledge_unit_id=node_a.id,
        status="active",
        build_revision_no=1,
    )
    session.add(node_b)
    session.flush()

    session.add(
        KnowledgeEdge(
            subject=subject_id,
            source_node_id=node_a.id,
            target_node_id=node_b.id,
            edge_type="prerequisite",
            status="active",
            build_revision_no=1,
        )
    )

    root_doc = KnowledgeDocument(
        subject=subject_id,
        chapter_index=1,
        order_index=1,
        title="代数基础",
        document_role="chapter",
        status="published",
        version_no=1,
        is_current=True,
    )
    session.add(root_doc)
    session.flush()

    session.add(
        KnowledgeDocument(
            subject=subject_id,
            root_document_id=root_doc.id,
            parent_document_id=root_doc.id,
            chapter_index=1,
            order_index=2,
            title="一元一次方程",
            document_role="subchapter",
            status="published",
            version_no=1,
            is_current=True,
        )
    )

    session.commit()
    return subject


def test_delete_subject_record_removes_self_referential_knowledge_graphs() -> None:
    session = _make_session()
    subject_id = "subj_abcd1234wxyz"
    _seed_subject_knowledge(session, subject_id=subject_id)

    with patch("app.workflows.support.subjects.lib.deletion._delete_subject_directory"):
        result = delete_subject_record(
            session,
            subject_id=subject_id,
            owner_user_id="local",
            force=True,
        )

    assert result.deleted is True
    assert result.subject_id == subject_id
    assert result.deleted_counts["knowledge_document"] == 2
    assert result.deleted_counts["knowledge_edge"] == 1
    assert result.deleted_counts["knowledge_unit"] == 2
    assert session.exec(select(Subject).where(Subject.slug == subject_id)).first() is None


def test_clear_subject_knowledge_handles_self_referential_rows() -> None:
    session = _make_session()
    subject_id = "subj_zyxw4321dcba"
    _seed_subject_knowledge(session, subject_id=subject_id)

    counts = clear_subject_knowledge(session, subject=subject_id)

    assert counts["knowledge_document"] == 2
    assert counts["knowledge_edge"] == 1
    assert counts["knowledge_unit"] == 2
    assert session.exec(select(Subject).where(Subject.slug == subject_id)).first() is not None
    assert session.exec(select(KnowledgeDocument).where(KnowledgeDocument.subject == subject_id)).first() is None
    assert session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject_id)).first() is None


def test_clear_subject_knowledge_rejects_when_exam_data_still_exists() -> None:
    session = _make_session()
    subject_id = "subj_exam1234abc"
    _seed_subject_knowledge(session, subject_id=subject_id)
    node = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject_id)).first()
    assert node is not None

    session.add(
        QuestionTemplate(
            subject=subject_id,
            knowledge_unit_id=node.id or 0,
            question_type="single_choice",
            difficulty="medium",
            stem="下面哪一项是一次方程？",
            stem_hash="template-stem-hash-1",
            answer="A",
            explanation="测试阻塞清空知识时使用。",
            status="active",
        )
    )
    session.commit()

    try:
        clear_subject_knowledge(session, subject=subject_id)
    except KnowledgeClearConflictError as exc:
        assert "题模板" in exc.detail
    else:
        raise AssertionError("expected KnowledgeClearConflictError when exam data exists")
