"""Repository helpers for retrieval chunks and embeddings."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
import structlog
from sqlmodel import Session, select

from app.core.database import require_vec_ready
from app.models import RetrievalChunk, Subject
from app.utils.time import utcnow

logger = structlog.get_logger()


def bulk_create_chunks(session: Session, chunks: list[RetrievalChunk]) -> list[RetrievalChunk]:
    for chunk in chunks:
        session.add(chunk)
    session.commit()
    for chunk in chunks:
        session.refresh(chunk)
    return chunks


def list_chunks_by_source(
    session: Session,
    *,
    source_type: str,
    source_id: int,
) -> list[RetrievalChunk]:
    stmt = (
        select(RetrievalChunk)
        .where(RetrievalChunk.source_type == source_type, RetrievalChunk.source_id == source_id)
        .order_by(RetrievalChunk.chunk_index.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def get_chunk_by_id(session: Session, chunk_id: int) -> RetrievalChunk | None:
    return session.get(RetrievalChunk, chunk_id)


def get_chunks_by_build_session(session: Session, build_session_id: str) -> list[RetrievalChunk]:
    stmt = (
        select(RetrievalChunk)
        .where(RetrievalChunk.build_session_id == build_session_id)
        .order_by(RetrievalChunk.source_type.asc(), RetrievalChunk.source_id.asc(), RetrievalChunk.chunk_index.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def delete_chunks_by_source(
    session: Session,
    *,
    source_type: str,
    source_ids: list[int],
) -> int:
    if not source_ids:
        return 0
    chunks = list(
        session.exec(
            select(RetrievalChunk).where(
                RetrievalChunk.source_type == source_type,
                RetrievalChunk.source_id.in_(source_ids),  # type: ignore[union-attr]
            )
        ).all()
    )
    chunk_ids = [int(chunk.id) for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        delete_embeddings_by_chunk_ids(session, chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    session.commit()
    return len(chunks)


def bulk_insert_embeddings(
    session: Session,
    chunk_ids: list[int],
    embeddings: list[list[float]],
) -> None:
    require_vec_ready()
    if not chunk_ids or not embeddings:
        return
    if len(chunk_ids) != len(embeddings):
        raise ValueError(
            "chunk_ids and embeddings must have the same length. "
            f"Got {len(chunk_ids)} chunk_ids and {len(embeddings)} embeddings."
        )

    connection = session.connection()
    params = {f"chunk_id_{index}": value for index, value in enumerate(chunk_ids)}
    placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
    connection.execute(
        sa.text(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})"),
        params,
    )
    for chunk_id, embedding in zip(chunk_ids, embeddings):
        connection.execute(
            sa.text("INSERT INTO chunk_embeddings(chunk_id, embedding) VALUES (:chunk_id, :embedding)"),
            {"chunk_id": chunk_id, "embedding": str(embedding)},
        )
    session.commit()
    logger.info(
        "bulk_insert_embeddings_completed",
        chunk_count=len(chunk_ids),
        embedding_dim=len(embeddings[0]) if embeddings else 0,
    )


def delete_embeddings_by_chunk_ids(session: Session, chunk_ids: list[int]) -> None:
    if not chunk_ids:
        return

    connection = session.connection()
    params = {f"chunk_id_{index}": value for index, value in enumerate(chunk_ids)}
    placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
    connection.execute(
        sa.text(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})"),
        params,
    )
    session.commit()


@dataclass
class ChunkSearchResult:
    chunk: RetrievalChunk
    score: float


def vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    require_vec_ready()
    if top_k <= 0:
        return []

    connection = session.connection()
    rows = connection.execute(
        sa.text(
            """
            SELECT ce.chunk_id, ce.distance
            FROM chunk_embeddings ce
            WHERE ce.chunk_id IN (
                SELECT c.id
                FROM retrieval_chunk c
                JOIN subject s ON c.subject_id = s.id
                WHERE s.slug = :subject
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


def touch_chunk(session: Session, chunk: RetrievalChunk) -> RetrievalChunk:
    chunk.updated_at = utcnow()
    session.add(chunk)
    session.commit()
    session.refresh(chunk)
    return chunk
