"""知识集合数据访问层。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.core.database import require_vec_ready
from app.models import (
    DocBuildJob,
    DocSet,
    DocSetSourceFile,
    Document,
    DocumentChunk,
    DocumentOutlineNode,
)

_UNSET = object()


def create_doc_set(session: Session, doc_set: DocSet) -> DocSet:
    """创建知识集合。"""

    session.add(doc_set)
    session.commit()
    session.refresh(doc_set)
    return doc_set


def get_doc_set_by_id(session: Session, doc_set_id: int) -> DocSet | None:
    """按 ID 查询知识集合。"""

    return session.get(DocSet, doc_set_id)


def list_doc_sets_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list[DocSet], int]:
    """分页查询知识集合。"""

    total = session.exec(select(func.count()).select_from(DocSet).where(DocSet.subject == subject)).one()
    stmt = (
        select(DocSet)
        .where(DocSet.subject == subject)
        .order_by(DocSet.updated_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def delete_doc_set(session: Session, doc_set: DocSet) -> None:
    """删除知识集合本体。"""

    session.delete(doc_set)
    session.commit()


def create_doc_build_job(session: Session, job: DocBuildJob) -> DocBuildJob:
    """创建知识构建任务。"""

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_doc_build_job_by_id(session: Session, job_id: int) -> DocBuildJob | None:
    """按 ID 查询构建任务。"""

    return session.get(DocBuildJob, job_id)


def get_latest_doc_build_job(session: Session, doc_set_id: int) -> DocBuildJob | None:
    """读取最近一次构建任务。"""

    stmt = (
        select(DocBuildJob)
        .where(DocBuildJob.doc_set_id == doc_set_id)
        .order_by(DocBuildJob.created_at.desc())  # type: ignore[union-attr]
        .limit(1)
    )
    return session.exec(stmt).first()


def list_doc_build_jobs(session: Session, doc_set_id: int) -> list[DocBuildJob]:
    """读取一个知识集合的全部构建任务。"""

    stmt = (
        select(DocBuildJob)
        .where(DocBuildJob.doc_set_id == doc_set_id)
        .order_by(DocBuildJob.created_at.desc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def update_doc_build_job(
    session: Session,
    job_id: int,
    *,
    status: str | None = None,
    progress: int | None = None,
    current_step: str | None | object = _UNSET,
    message: str | None = None,
    error_message: str | None | object = _UNSET,
) -> DocBuildJob | None:
    """更新知识构建任务。"""

    job = session.get(DocBuildJob, job_id)
    if job is None:
        return None
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if current_step is not _UNSET:
        job.current_step = current_step
    if message is not None:
        job.message = message
    if error_message is not _UNSET:
        job.error_message = error_message
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def delete_doc_build_jobs_by_docset(session: Session, doc_set_id: int) -> int:
    """删除知识集合的全部构建任务。"""

    jobs = list_doc_build_jobs(session, doc_set_id)
    count = len(jobs)
    for job in jobs:
        session.delete(job)
    session.commit()
    return count


def bulk_create_doc_set_sources(
    session: Session,
    links: list[DocSetSourceFile],
) -> list[DocSetSourceFile]:
    """批量创建知识集合与文件关联。"""

    for link in links:
        session.add(link)
    session.commit()
    for link in links:
        session.refresh(link)
    return links


def list_doc_set_source_files(session: Session, doc_set_id: int) -> list[DocSetSourceFile]:
    """读取知识集合的源文件关联。"""

    stmt = (
        select(DocSetSourceFile)
        .where(DocSetSourceFile.doc_set_id == doc_set_id)
        .order_by(DocSetSourceFile.id.asc())
    )
    return list(session.exec(stmt).all())


def delete_doc_set_source_links(session: Session, doc_set_id: int) -> int:
    """删除知识集合的源文件关联。"""

    links = list_doc_set_source_files(session, doc_set_id)
    count = len(links)
    for link in links:
        session.delete(link)
    session.commit()
    return count


def bulk_create_documents(session: Session, documents: list[Document]) -> list[Document]:
    """批量创建文档。"""

    for document in documents:
        session.add(document)
    session.commit()
    for document in documents:
        session.refresh(document)
    return documents


def get_document_by_id(session: Session, document_id: int) -> Document | None:
    """按 ID 查询文档。"""

    return session.get(Document, document_id)


def list_documents_by_doc_set(session: Session, doc_set_id: int) -> list[Document]:
    """读取知识集合下的文档。"""

    stmt = (
        select(Document)
        .where(Document.doc_set_id == doc_set_id)
        .order_by(Document.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def count_documents_by_doc_set(session: Session, doc_set_id: int) -> int:
    """统计知识集合的文档数量。"""

    return session.exec(
        select(func.count()).select_from(Document).where(Document.doc_set_id == doc_set_id)
    ).one()


def update_document_content(
    session: Session,
    document_id: int,
    markdown_content: str,
) -> Document | None:
    """更新文档内容。"""

    document = session.get(Document, document_id)
    if document is None:
        return None
    document.markdown_content = markdown_content
    document.updated_at = datetime.utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def update_document_step(
    session: Session,
    document_id: int,
    current_step: str | None,
) -> Document | None:
    """更新文档处理步骤。"""

    document = session.get(Document, document_id)
    if document is None:
        return None
    document.current_step = current_step
    document.updated_at = datetime.utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def bulk_create_graph_nodes(
    session: Session,
    nodes: list[DocumentOutlineNode],
) -> list[DocumentOutlineNode]:
    """批量创建大纲节点。"""

    for node in nodes:
        session.add(node)
    session.commit()
    for node in nodes:
        session.refresh(node)
    return nodes


def create_graph_node(session: Session, node: DocumentOutlineNode) -> DocumentOutlineNode:
    """创建单个大纲节点。"""

    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def get_graph_nodes_by_document_id(
    session: Session,
    document_id: int,
) -> list[DocumentOutlineNode]:
    """读取文档大纲。"""

    stmt = (
        select(DocumentOutlineNode)
        .where(DocumentOutlineNode.document_id == document_id)
        .order_by(DocumentOutlineNode.order_index)
    )
    return list(session.exec(stmt).all())


def list_graph_nodes_by_subject(session: Session, subject: str) -> list[DocumentOutlineNode]:
    """读取学科下全部大纲节点。"""

    stmt = (
        select(DocumentOutlineNode)
        .join(Document, DocumentOutlineNode.document_id == Document.id)
        .where(Document.subject == subject)
        .order_by(DocumentOutlineNode.document_id, DocumentOutlineNode.order_index)
    )
    return list(session.exec(stmt).all())


def bulk_create_chunks(
    session: Session,
    chunks: list[DocumentChunk],
) -> list[DocumentChunk]:
    """批量创建切块。"""

    for chunk in chunks:
        session.add(chunk)
    session.commit()
    for chunk in chunks:
        session.refresh(chunk)
    return chunks


def get_chunks_by_document_id(session: Session, document_id: int) -> list[DocumentChunk]:
    """读取文档切块。"""

    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(session.exec(stmt).all())


def get_chunk_by_id(session: Session, chunk_id: int) -> DocumentChunk | None:
    """按 ID 获取单个切块。"""
    return session.get(DocumentChunk, chunk_id)


def get_document_by_id(session: Session, document_id: int) -> Document | None:
    """按 ID 获取单个文档。"""
    return session.get(Document, document_id)


def count_chunks_by_doc_set(session: Session, doc_set_id: int) -> int:
    """统计知识集合切块数。"""

    stmt = (
        select(func.count())
        .select_from(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.doc_set_id == doc_set_id)
    )
    return session.exec(stmt).one()


def bulk_insert_embeddings(
    session: Session,
    chunk_ids: list[int],
    embeddings: list[list[float]],
) -> None:
    """批量写入向量表。"""

    require_vec_ready()
    conn = session.connection()
    for chunk_id, embedding in zip(chunk_ids, embeddings):
        conn.execute(
            sa.text(
                "INSERT OR REPLACE INTO chunk_embeddings(chunk_id, embedding) "
                "VALUES (:chunk_id, :embedding)"
            ),
            {"chunk_id": chunk_id, "embedding": str(embedding)},
        )
    session.commit()


def delete_embeddings_by_chunk_ids(session: Session, chunk_ids: list[int]) -> None:
    """删除切块向量。"""

    if not chunk_ids:
        return
    conn = session.connection()
    params = {f"chunk_id_{index}": value for index, value in enumerate(chunk_ids)}
    placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
    try:
        conn.execute(
            sa.text(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})"),
            params,
        )
        session.commit()
    except Exception:
        session.rollback()


def clear_doc_set_generated_data(session: Session, doc_set_id: int) -> None:
    """清空知识集合下的文档、大纲、切块和向量。"""

    documents = list_documents_by_doc_set(session, doc_set_id)
    document_ids = [document.id for document in documents if document.id is not None]
    chunk_ids: list[int] = []

    for document_id in document_ids:
        for chunk in get_chunks_by_document_id(session, document_id):
            if chunk.id is not None:
                chunk_ids.append(chunk.id)
                session.delete(chunk)
        for node in get_graph_nodes_by_document_id(session, document_id):
            session.delete(node)
        document = session.get(Document, document_id)
        if document is not None:
            session.delete(document)

    session.commit()
    delete_embeddings_by_chunk_ids(session, chunk_ids)


def delete_doc_set_cascade(session: Session, doc_set_id: int) -> bool:
    """级联删除知识集合及其相关数据。"""

    doc_set = session.get(DocSet, doc_set_id)
    if doc_set is None:
        return False
    clear_doc_set_generated_data(session, doc_set_id)
    delete_doc_build_jobs_by_docset(session, doc_set_id)
    delete_doc_set_source_links(session, doc_set_id)
    session.delete(doc_set)
    session.commit()
    return True


@dataclass
class ChunkSearchResult:
    """向量检索结果。"""

    chunk: DocumentChunk
    score: float


def vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    """执行 sqlite-vec 检索。"""

    require_vec_ready()
    conn = session.connection()
    rows = conn.execute(
        sa.text(
            """
            SELECT
                ce.chunk_id,
                ce.distance
            FROM chunk_embeddings ce
            JOIN document_chunk c ON c.id = ce.chunk_id
            JOIN document d ON d.id = c.document_id
            WHERE d.subject = :subject
              AND ce.embedding MATCH :query_embedding
            ORDER BY ce.distance
            LIMIT :top_k
            """
        ),
        {
            "subject": subject,
            "query_embedding": str(query_embedding),
            "top_k": top_k,
        },
    ).fetchall()

    results: list[ChunkSearchResult] = []
    for row in rows:
        chunk = session.get(DocumentChunk, row[0])
        if chunk is None:
            continue
        distance = row[1]
        score = 1.0 / (1.0 + distance) if distance >= 0 else 0.0
        results.append(ChunkSearchResult(chunk=chunk, score=score))
    return results
