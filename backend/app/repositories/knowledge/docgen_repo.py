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


def get_docs_by_subject(
    session: Session,
    subject: str,
    *,
    status: str | None = None,
) -> list[KnowledgeDoc]:
    """按学科查询知识文档，并按章节顺序返回。"""

    statement = (
        select(KnowledgeDoc)
        .where(KnowledgeDoc.subject == subject)
        .order_by(KnowledgeDoc.chapter_index)
    )
    if status is not None:
        statement = statement.where(KnowledgeDoc.status == status)
    return list(session.exec(statement).all())


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


def delete_docs_by_subject(session: Session, subject: str) -> int:
    """删除学科下的全部知识文档，返回删除数量。"""

    docs = get_docs_by_subject(session, subject)
    deleted_count = len(docs)
    for doc in docs:
        session.delete(doc)
    session.commit()
    return deleted_count
