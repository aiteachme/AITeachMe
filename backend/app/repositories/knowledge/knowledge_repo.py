"""Repository helpers for retrieval chunks and embeddings."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
import structlog
from sqlmodel import Session, select

from app.core.database import is_vec_ready
from app.models import RawFile, RetrievalChunk
from app.utils.time import utcnow

logger = structlog.get_logger()


def bulk_create_documents(session: Session, documents: list[RawFile]) -> list[RawFile]:
    """Persist or update raw-file backed document records."""

    persisted: list[RawFile] = []
    for document in documents:
        if document.id is None:
            session.add(document)
            persisted.append(document)
            continue

        existing = session.get(RawFile, document.id)
        if existing is None:
            session.add(document)
            persisted.append(document)
            continue

        if document.markdown_content:
            existing.markdown_content = document.markdown_content
        if document.current_step is not None:
            existing.current_step = document.current_step
        if document.markdown_path is not None:
            existing.markdown_path = document.markdown_path
        if document.markdown_uri is not None:
            existing.markdown_uri = document.markdown_uri
        existing.updated_at = utcnow()
        session.add(existing)
        persisted.append(existing)
    session.commit()
    for document in persisted:
        session.refresh(document)
    return persisted


def get_document_by_id(session: Session, document_id: int) -> RawFile | None:
    return session.get(RawFile, document_id)


def get_documents_by_source_file_ids(
    session: Session,
    *,
    subject: str,
    source_file_ids: list[int],
) -> list[RawFile]:
    if not source_file_ids:
        return []
    statement = select(RawFile).where(
        RawFile.subject == subject,
        RawFile.id.in_(source_file_ids),
    )
    return list(session.exec(statement).all())


def update_document_content(
    session: Session,
    document_id: int,
    markdown_content: str,
) -> RawFile | None:
    document = session.get(RawFile, document_id)
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
) -> RawFile | None:
    document = session.get(RawFile, document_id)
    if document is None:
        return None
    document.current_step = current_step
    document.updated_at = utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def bulk_create_chunks(session: Session, chunks: list[RetrievalChunk]) -> list[RetrievalChunk]:
    for chunk in chunks:
        session.add(chunk)
    session.commit()
    for chunk in chunks:
        session.refresh(chunk)
    return chunks


def get_chunks_by_document_id(session: Session, document_id: int) -> list[RetrievalChunk]:
    statement = (
        select(RetrievalChunk)
        .where(RetrievalChunk.document_id == document_id)
        .order_by(RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_document_ids(session: Session, document_ids: list[int]) -> list[RetrievalChunk]:
    if not document_ids:
        return []
    statement = (
        select(RetrievalChunk)
        .where(RetrievalChunk.document_id.in_(document_ids))
        .order_by(RetrievalChunk.document_id, RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_source_file_ids(
    session: Session,
    *,
    subject: str,
    source_file_ids: list[int],
) -> list[RetrievalChunk]:
    if not source_file_ids:
        return []
    statement = (
        select(RetrievalChunk)
        .where(
            RetrievalChunk.subject == subject,
            RetrievalChunk.document_id.in_(source_file_ids),
        )
        .order_by(RetrievalChunk.document_id, RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_build_session(session: Session, build_session_id: str) -> list[RetrievalChunk]:
    statement = (
        select(RetrievalChunk)
        .where(RetrievalChunk.build_session_id == build_session_id)
        .order_by(RetrievalChunk.document_id, RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunk_by_id(session: Session, chunk_id: int) -> RetrievalChunk | None:
    return session.get(RetrievalChunk, chunk_id)


def delete_chunks_by_document_ids(session: Session, document_ids: list[int]) -> int:
    chunks = get_chunks_by_document_ids(session, document_ids)
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        delete_embeddings_by_chunk_ids(session, chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    session.commit()
    return len(chunks)


def delete_chunks_by_ids(session: Session, chunk_ids: list[int]) -> int:
    if not chunk_ids:
        return 0
    chunks = [
        chunk
        for chunk_id in chunk_ids
        if (chunk := session.get(RetrievalChunk, chunk_id)) is not None
    ]
    if not chunks:
        return 0
    delete_embeddings_by_chunk_ids(session, [chunk.id for chunk in chunks if chunk.id is not None])
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
    documents = get_documents_by_source_file_ids(
        session,
        subject=subject,
        source_file_ids=source_file_ids,
    )
    document_ids = [document.id for document in documents if document.id is not None]
    chunk_count = delete_chunks_by_document_ids(session, document_ids)
    return len(documents), chunk_count


def bulk_insert_embeddings(
    session: Session,
    chunk_ids: list[int],
    embeddings: list[list[float]],
) -> None:
    if not is_vec_ready():
        logger.warning("bulk_insert_embeddings_skipped", reason="sqlite-vec unavailable")
        return
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
    if not chunk_ids or not is_vec_ready():
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

    chunk: RetrievalChunk
    score: float


def vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    if not is_vec_ready():
        logger.warning("vector_search_skipped", reason="sqlite-vec unavailable", subject=subject)
        return []
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
                FROM retrieval_chunk c
                WHERE c.subject = :subject
                  AND c.is_active = 1
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
        chunk = session.get(RetrievalChunk, row[0])
        if chunk is None:
            continue
        distance = row[1]
        score = 1.0 / (1.0 + distance) if distance >= 0 else 0.0
        results.append(ChunkSearchResult(chunk=chunk, score=score))
    return results
