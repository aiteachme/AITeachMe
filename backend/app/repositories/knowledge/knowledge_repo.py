"""Repository helpers for source documents and embeddings."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
import structlog
from sqlmodel import Session, select

from app.core.database import require_vec_ready
from app.models import Document, DocumentChunk
from app.utils.time import utcnow

logger = structlog.get_logger()


def bulk_create_documents(session: Session, documents: list[Document]) -> list[Document]:
    """Persist documents and refresh generated ids."""

    for document in documents:
        session.add(document)
    session.commit()
    for document in documents:
        session.refresh(document)
    return documents


def get_document_by_id(session: Session, document_id: int) -> Document | None:
    """Fetch a single document by id."""

    return session.get(Document, document_id)


def get_documents_by_source_file_ids(
    session: Session,
    *,
    subject: str,
    source_file_ids: list[int],
) -> list[Document]:
    """Fetch documents for one subject and a set of raw files."""

    if not source_file_ids:
        return []
    statement = select(Document).where(
        Document.subject == subject,
        Document.source_file_id.in_(source_file_ids),
    )
    return list(session.exec(statement).all())


def update_document_content(
    session: Session,
    document_id: int,
    markdown_content: str,
) -> Document | None:
    """Update the stored document markdown."""

    document = session.get(Document, document_id)
    if document is None:
        return None
    document.markdown_content = markdown_content
    document.updated_at = utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def update_document_step(
    session: Session,
    document_id: int,
    current_step: str | None,
) -> Document | None:
    """Update the materialization step label."""

    document = session.get(Document, document_id)
    if document is None:
        return None
    document.current_step = current_step
    document.updated_at = utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def bulk_create_chunks(session: Session, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Persist document chunks and refresh generated ids."""

    for chunk in chunks:
        session.add(chunk)
    session.commit()
    for chunk in chunks:
        session.refresh(chunk)
    return chunks


def get_chunks_by_document_id(session: Session, document_id: int) -> list[DocumentChunk]:
    """Fetch chunks for one document ordered by chunk index."""

    statement = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_document_ids(session: Session, document_ids: list[int]) -> list[DocumentChunk]:
    """Fetch chunks for many documents."""

    if not document_ids:
        return []
    statement = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id.in_(document_ids))
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_build_session(session: Session, build_session_id: str) -> list[DocumentChunk]:
    """Fetch all chunks created in one unified build session."""

    statement = (
        select(DocumentChunk)
        .where(DocumentChunk.build_session_id == build_session_id)
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunk_by_id(session: Session, chunk_id: int) -> DocumentChunk | None:
    """Fetch one chunk by id."""

    return session.get(DocumentChunk, chunk_id)


def delete_chunks_by_document_ids(session: Session, document_ids: list[int]) -> int:
    """Delete chunks and embeddings for a set of documents."""

    chunks = get_chunks_by_document_ids(session, document_ids)
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        delete_embeddings_by_chunk_ids(session, chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    session.commit()
    return len(chunks)


def delete_documents_by_source_file_ids(
    session: Session,
    *,
    subject: str,
    source_file_ids: list[int],
) -> tuple[int, int]:
    """Delete documents for selected raw files and all of their chunks."""

    documents = get_documents_by_source_file_ids(
        session,
        subject=subject,
        source_file_ids=source_file_ids,
    )
    document_ids = [document.id for document in documents if document.id is not None]
    chunk_count = delete_chunks_by_document_ids(session, document_ids)
    for document in documents:
        session.delete(document)
    session.commit()
    return len(documents), chunk_count


def bulk_insert_embeddings(
    session: Session,
    chunk_ids: list[int],
    embeddings: list[list[float]],
) -> None:
    """Replace embeddings for a set of chunk ids."""

    require_vec_ready()
    if not chunk_ids or not embeddings:
        return
    if len(chunk_ids) != len(embeddings):
        raise ValueError(
            "chunk_ids and embeddings must have the same length. "
            f"Got {len(chunk_ids)} chunk_ids and {len(embeddings)} embeddings."
        )

    connection = session.connection()
    try:
        params = {f"chunk_id_{index}": value for index, value in enumerate(chunk_ids)}
        placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
        connection.execute(
            sa.text(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})"),
            params,
        )
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            connection.execute(
                sa.text(
                    "INSERT INTO chunk_embeddings(chunk_id, embedding) "
                    "VALUES (:chunk_id, :embedding)"
                ),
                {"chunk_id": chunk_id, "embedding": str(embedding)},
            )
        session.commit()
        logger.info(
            "bulk_insert_embeddings_completed",
            chunk_count=len(chunk_ids),
            embedding_dim=len(embeddings[0]) if embeddings else 0,
        )
    except Exception:
        session.rollback()
        logger.exception(
            "bulk_insert_embeddings_failed",
            chunk_count=len(chunk_ids),
            embedding_dim=len(embeddings[0]) if embeddings else 0,
            chunk_ids_preview=chunk_ids[:5],
        )
        raise


def delete_embeddings_by_chunk_ids(session: Session, chunk_ids: list[int]) -> None:
    """Delete embeddings for the provided chunk ids."""

    if not chunk_ids:
        return

    connection = session.connection()
    params = {f"chunk_id_{index}": value for index, value in enumerate(chunk_ids)}
    placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
    try:
        connection.execute(
            sa.text(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})"),
            params,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


@dataclass
class ChunkSearchResult:
    """Vector search result item."""

    chunk: DocumentChunk
    score: float


def vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    """Run sqlite-vec search against subject chunks."""

    require_vec_ready()
    if top_k <= 0:
        return []

    connection = session.connection()
    rows = connection.execute(
        sa.text(
            """
            SELECT
                ce.chunk_id,
                ce.distance
            FROM chunk_embeddings ce
            WHERE ce.chunk_id IN (
                SELECT c.id
                FROM document_chunk c
                JOIN document d ON d.id = c.document_id
                WHERE d.subject = :subject
            )
              AND ce.embedding MATCH :query_embedding
              AND k = :top_k
            ORDER BY ce.distance
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
