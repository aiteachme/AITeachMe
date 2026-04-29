"""知识文档数据访问。"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.knowledge_doc import KnowledgeDoc
from app.utils.time import utcnow


def bulk_create_knowledge_docs(session: Session, docs: list[KnowledgeDoc]) -> list[KnowledgeDoc]:
    """批量创建知识文档。"""

    for doc in docs:
        session.add(doc)
    session.commit()
    for doc in docs:
        session.refresh(doc)
    return docs


def get_docs_by_course(
    session: Session,
    course_id: str,
    *,
    status: str | None = None,
    only_current: bool | None = None,
    version_no: int | None = None,
) -> list[KnowledgeDoc]:
    """按课程查询知识文档，并按章节顺序返回。"""

    statement = (
        select(KnowledgeDoc)
        .where(KnowledgeDoc.course_id == course_id)
        .order_by(KnowledgeDoc.version_no, KnowledgeDoc.chapter_index)
    )
    if status is not None:
        statement = statement.where(KnowledgeDoc.status == status)
    if only_current is not None:
        statement = statement.where(KnowledgeDoc.is_current.is_(only_current))
    if version_no is not None:
        statement = statement.where(KnowledgeDoc.version_no == version_no)
    return list(session.exec(statement).all())


def get_current_published_docs(session: Session, course_id: str) -> list[KnowledgeDoc]:
    """Return current published chapter docs for one course_id in display order."""

    statement = (
        select(KnowledgeDoc)
        .where(
            KnowledgeDoc.course_id == course_id,
            KnowledgeDoc.is_current.is_(True),
            KnowledgeDoc.status == "published",
        )
        .order_by(KnowledgeDoc.order_index, KnowledgeDoc.chapter_index, KnowledgeDoc.id)
    )
    return list(session.exec(statement).all())


def get_latest_version_no(session: Session, course_id: str) -> int:
    """Return the latest published version number for one course_id."""

    statement = (
        select(KnowledgeDoc.version_no)
        .where(KnowledgeDoc.course_id == course_id)
        .order_by(KnowledgeDoc.version_no.desc(), KnowledgeDoc.id.desc())
    )
    latest = session.exec(statement).first()
    return int(latest or 0)


def get_doc_by_id(session: Session, doc_id: int) -> KnowledgeDoc | None:
    """按 ID 查询单篇知识文档。"""

    return session.get(KnowledgeDoc, doc_id)


def update_doc_status(session: Session, doc_id: int, status: str) -> KnowledgeDoc | None:
    """更新知识文档状态。"""

    doc = session.get(KnowledgeDoc, doc_id)
    if doc is None:
        return None
    doc.status = status
    doc.updated_at = utcnow()
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def delete_docs_by_course(session: Session, course_id: str) -> int:
    """删除课程下的全部知识文档，返回删除数量。"""

    docs = get_docs_by_course(session, course_id)
    deleted_count = len(docs)
    for doc in docs:
        session.delete(doc)
    session.commit()
    return deleted_count
