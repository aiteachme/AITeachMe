"""Persistence helpers for doc sets, documents, outlines, chunks, and vector search."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.core.database import require_vec_ready
from app.repositories.models import (
    DocBuildJob,
    DocSet,
    DocSetSourceFile,
    Document,
    DocumentChunk,
    DocumentOutlineNode,
)


def create_doc_set(session: Session, doc_set: DocSet) -> DocSet:
    session.add(doc_set)
    session.commit()
    session.refresh(doc_set)
    return doc_set


def get_doc_set_by_id(session: Session, doc_set_id: int) -> DocSet | None:
    return session.get(DocSet, doc_set_id)


def update_doc_set_status(
    session: Session,
    doc_set_id: int,
    *,
    build_status: str | None = None,
    title: str | None = None,
    description: str | None = None,
) -> DocSet | None:
    doc_set = session.get(DocSet, doc_set_id)
    if doc_set is None:
        return None
    if build_status is not None:
        doc_set.build_status = build_status
    if title is not None:
        doc_set.title = title
    if description is not None:
        doc_set.description = description
    doc_set.updated_at = datetime.utcnow()
    session.add(doc_set)
    session.commit()
    session.refresh(doc_set)
    return doc_set


def list_doc_sets_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DocSet], int]:
    count_stmt = select(func.count()).select_from(DocSet).where(DocSet.subject == subject)
    total = session.exec(count_stmt).one()

    stmt = (
        select(DocSet)
        .where(DocSet.subject == subject)
        .order_by(DocSet.updated_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def create_doc_build_job(session: Session, job: DocBuildJob) -> DocBuildJob:
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def get_doc_build_job_by_id(session: Session, job_id: int) -> DocBuildJob | None:
    return session.get(DocBuildJob, job_id)


def get_latest_doc_build_job(session: Session, doc_set_id: int) -> DocBuildJob | None:
    stmt = (
        select(DocBuildJob)
        .where(DocBuildJob.doc_set_id == doc_set_id)
        .order_by(DocBuildJob.created_at.desc())  # type: ignore[union-attr]
        .limit(1)
    )
    return session.exec(stmt).first()


def update_doc_build_job(
    session: Session,
    job_id: int,
    *,
    stage: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
) -> DocBuildJob | None:
    job = session.get(DocBuildJob, job_id)
    if job is None:
        return None
    if stage is not None:
        job.stage = stage
    if progress is not None:
        job.progress = progress
    if message is not None:
        job.message = message
    job.error = error
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def bulk_create_doc_set_sources(
    session: Session,
    links: list[DocSetSourceFile],
) -> list[DocSetSourceFile]:
    for link in links:
        session.add(link)
    session.commit()
    for link in links:
        session.refresh(link)
    return links


def list_doc_set_source_files(session: Session, doc_set_id: int) -> list[DocSetSourceFile]:
    stmt = (
        select(DocSetSourceFile)
        .where(DocSetSourceFile.doc_set_id == doc_set_id)
        .order_by(DocSetSourceFile.id.asc())
    )
    return list(session.exec(stmt).all())


def create_document(session: Session, document: Document) -> Document:
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def bulk_create_documents(session: Session, documents: list[Document]) -> list[Document]:
    for document in documents:
        session.add(document)
    session.commit()
    for document in documents:
        session.refresh(document)
    return documents


def get_document_by_id(session: Session, document_id: int) -> Document | None:
    return session.get(Document, document_id)


def update_document_stage(
    session: Session,
    document_id: int,
    stage: str,
) -> Document | None:
    document = session.get(Document, document_id)
    if document is None:
        return None
    document.pipeline_stage = stage
    document.updated_at = datetime.utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def update_document_content(
    session: Session,
    document_id: int,
    markdown_content: str,
) -> Document | None:
    document = session.get(Document, document_id)
    if document is None:
        return None
    document.markdown_content = markdown_content
    document.updated_at = datetime.utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def list_documents_by_doc_set(
    session: Session,
    doc_set_id: int,
) -> list[Document]:
    stmt = (
        select(Document)
        .where(Document.doc_set_id == doc_set_id)
        .order_by(Document.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def count_documents_by_doc_set(session: Session, doc_set_id: int) -> int:
    stmt = select(func.count()).select_from(Document).where(Document.doc_set_id == doc_set_id)
    return session.exec(stmt).one()


def count_chunks_by_doc_set(session: Session, doc_set_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.doc_set_id == doc_set_id)
    )
    return session.exec(stmt).one()


def create_graph_node(session: Session, node: DocumentOutlineNode) -> DocumentOutlineNode:
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def bulk_create_graph_nodes(
    session: Session,
    nodes: list[DocumentOutlineNode],
) -> list[DocumentOutlineNode]:
    for node in nodes:
        session.add(node)
    session.commit()
    for node in nodes:
        session.refresh(node)
    return nodes


def get_graph_nodes_by_document_id(
    session: Session,
    document_id: int,
) -> list[DocumentOutlineNode]:
    stmt = (
        select(DocumentOutlineNode)
        .where(DocumentOutlineNode.document_id == document_id)
        .order_by(DocumentOutlineNode.order_index)
    )
    return list(session.exec(stmt).all())


def list_graph_nodes_by_subject(
    session: Session,
    subject: str,
) -> list[DocumentOutlineNode]:
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
    for chunk in chunks:
        session.add(chunk)
    session.commit()
    for chunk in chunks:
        session.refresh(chunk)
    return chunks


def get_chunks_by_document_id(session: Session, document_id: int) -> list[DocumentChunk]:
    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(session.exec(stmt).all())


def bulk_insert_embeddings(
    session: Session,
    chunk_ids: list[int],
    embeddings: list[list[float]],
) -> None:
    require_vec_ready()
    conn = session.connection()
    for chunk_id, embedding in zip(chunk_ids, embeddings):
        conn.execute(
            sa.text(
                "INSERT OR REPLACE INTO chunk_embeddings(chunk_id, embedding) "
                "VALUES (:cid, :emb)"
            ),
            {"cid": chunk_id, "emb": str(embedding)},
        )
    session.commit()


@dataclass
class ChunkSearchResult:
    chunk: DocumentChunk
    score: float


def vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    require_vec_ready()
    conn = session.connection()

    sql = sa.text(
        """
        SELECT
            ce.chunk_id,
            ce.distance
        FROM chunk_embeddings ce
        JOIN document_chunk c ON c.id = ce.chunk_id
        JOIN document d ON d.id = c.document_id
        WHERE d.subject = :subject
          AND ce.embedding MATCH :query_emb
        ORDER BY ce.distance
        LIMIT :top_k
        """
    )

    rows = conn.execute(
        sql,
        {"subject": subject, "query_emb": str(query_embedding), "top_k": top_k},
    ).fetchall()

    results: list[ChunkSearchResult] = []
    for row in rows:
        chunk_id, distance = row[0], row[1]
        chunk = session.get(DocumentChunk, chunk_id)
        if chunk is not None:
            score = 1.0 / (1.0 + distance) if distance >= 0 else 0.0
            results.append(ChunkSearchResult(chunk=chunk, score=score))

    return results
