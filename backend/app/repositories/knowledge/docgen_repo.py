"""知识文档生成数据访问层。"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.knowledge_doc import DocGenJob, KnowledgeDoc
from app.utils.time import utcnow


# ── DocGenJob CRUD ──


def create_docgen_job(session: Session, job: DocGenJob) -> DocGenJob:
    """创建文档生成任务。"""

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_docgen_job(session: Session, job_id: int) -> DocGenJob | None:
    """按 ID 查询任务。"""

    return session.get(DocGenJob, job_id)


def get_latest_docgen_job_by_subject(session: Session, subject: str) -> DocGenJob | None:
    """按学科查询最近一次 DocGen 任务。"""

    stmt = (
        select(DocGenJob)
        .where(DocGenJob.subject == subject)
        .order_by(DocGenJob.created_at.desc())  # type: ignore[union-attr]
        .limit(1)
    )
    return session.exec(stmt).first()


def update_docgen_job(
    session: Session,
    job_id: int,
    *,
    status: str | None = None,
    progress: int | None = None,
    current_step: str | None = None,
    total_chapters: int | None = None,
    completed_chapters: int | None = None,
    error_message: str | None = None,
) -> DocGenJob | None:
    """更新任务状态。"""

    job = session.get(DocGenJob, job_id)
    if job is None:
        return None
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if current_step is not None:
        job.current_step = current_step
    if total_chapters is not None:
        job.total_chapters = total_chapters
    if completed_chapters is not None:
        job.completed_chapters = completed_chapters
    if error_message is not None:
        job.error_message = error_message
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# ── KnowledgeDoc CRUD ──


def bulk_create_knowledge_docs(
    session: Session,
    docs: list[KnowledgeDoc],
) -> list[KnowledgeDoc]:
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
    """按学科查询知识文档（按 chapter_index 排序）。"""

    stmt = (
        select(KnowledgeDoc)
        .where(KnowledgeDoc.subject == subject)
        .order_by(KnowledgeDoc.chapter_index)
    )
    if status is not None:
        stmt = stmt.where(KnowledgeDoc.status == status)
    return list(session.exec(stmt).all())


def get_doc_by_id(session: Session, doc_id: int) -> KnowledgeDoc | None:
    """按 ID 查询单篇知识文档。"""

    return session.get(KnowledgeDoc, doc_id)


def update_doc_status(
    session: Session,
    doc_id: int,
    status: str,
) -> KnowledgeDoc | None:
    """更新文档状态。"""

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
    """删除学科下所有知识文档，返回删除数量。"""

    docs = get_docs_by_subject(session, subject)
    count = len(docs)
    for doc in docs:
        session.delete(doc)
    session.commit()
    return count
