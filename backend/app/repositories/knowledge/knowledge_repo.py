"""Repository helpers for retrieval chunks and embeddings."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
import structlog
from sqlmodel import Session, select

from app.shared.infra.config import get_settings
from app.shared.infra.database import (
    ensure_subject_vec_table,
    get_engine,
    get_vector_table_dim,
    is_postgres,
    is_sqlite,
    is_vec_ready,
    quote_sqlite_identifier,
    vector_table_exists,
)
from app.shared.infra.subject_embeddings import (
    SubjectEmbeddingMode,
    build_subject_vector_table_name,
    get_legacy_vector_table_name,
    get_subject_embedding_binding,
)
from app.models import RawFile, RetrievalChunk, Subject
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


def delete_chunks_by_document_ids(session: Session, *, subject: str, document_ids: list[int]) -> int:
    chunks = get_chunks_by_document_ids(session, document_ids)
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        delete_embeddings_by_chunk_ids(session, subject=subject, chunk_ids=chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    session.commit()
    return len(chunks)


def delete_chunks_by_ids(session: Session, *, subject: str | None = None, chunk_ids: list[int]) -> int:
    if not chunk_ids:
        return 0
    chunks = [
        chunk
        for chunk_id in chunk_ids
        if (chunk := session.get(RetrievalChunk, chunk_id)) is not None
    ]
    if not chunks:
        return 0
    resolved_subject = subject or chunks[0].subject
    delete_embeddings_by_chunk_ids(
        session,
        subject=resolved_subject,
        chunk_ids=[chunk.id for chunk in chunks if chunk.id is not None],
    )
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
    chunk_count = delete_chunks_by_document_ids(session, subject=subject, document_ids=document_ids)
    return len(documents), chunk_count


def _get_subject_record(session: Session, subject: str) -> Subject | None:
    return session.exec(select(Subject).where(Subject.slug == subject)).first()


def _get_subject_binding(session: Session, subject: str):
    subject_record = _get_subject_record(session, subject)
    if subject_record is None:
        return None
    return get_subject_embedding_binding(subject_record)


def _delete_embeddings_from_table(
    connection: sa.Connection,
    *,
    table_name: str,
    chunk_ids: list[int],
) -> None:
    if not chunk_ids or not vector_table_exists(connection, table_name):
        return

    placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
    params = {f"chunk_id_{index}": chunk_id for index, chunk_id in enumerate(chunk_ids)}
    quoted_table_name = quote_sqlite_identifier(table_name)
    connection.execute(
        sa.text(f"DELETE FROM {quoted_table_name} WHERE chunk_id IN ({placeholders})"),
        params,
    )


def _count_embeddings_for_chunk_ids(
    connection: sa.Connection,
    *,
    table_name: str,
    chunk_ids: list[int],
) -> int:
    if not chunk_ids or not vector_table_exists(connection, table_name):
        return 0

    placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
    params = {f"chunk_id_{index}": chunk_id for index, chunk_id in enumerate(chunk_ids)}
    quoted_table_name = quote_sqlite_identifier(table_name)
    row = connection.execute(
        sa.text(f"SELECT COUNT(*) FROM {quoted_table_name} WHERE chunk_id IN ({placeholders})"),
        params,
    ).first()
    return int(row[0]) if row is not None else 0


def count_embeddings_for_chunk_ids(
    session: Session,
    *,
    table_name: str,
    chunk_ids: list[int],
) -> int:
    return _count_embeddings_for_chunk_ids(
        session.connection(),
        table_name=table_name,
        chunk_ids=chunk_ids,
    )


def _legacy_table_for_subject(
    session: Session,
    *,
    subject: str,
    chunk_ids: list[int],
) -> str | None:
    table_name = get_legacy_vector_table_name()
    if _count_embeddings_for_chunk_ids(session.connection(), table_name=table_name, chunk_ids=chunk_ids) <= 0:
        return None
    return table_name


def _resolve_insert_table(
    session: Session,
    *,
    subject: str,
    embedding_dim: int,
) -> str | None:
    binding = _get_subject_binding(session, subject)
    if binding is not None and binding.mode == SubjectEmbeddingMode.DISABLED:
        return None
    table_name = (
        binding.vector_table
        if binding is not None and binding.vector_table
        else build_subject_vector_table_name(subject)
    )
    ensure_subject_vec_table(get_engine(), subject=subject, embedding_dim=embedding_dim)
    return table_name


def _resolve_search_table(
    session: Session,
    *,
    subject: str,
    query_embedding_dim: int,
) -> str | None:
    binding = _get_subject_binding(session, subject)
    connection = session.connection()

    if binding is not None and binding.mode == SubjectEmbeddingMode.DISABLED:
        return None

    if binding is not None and binding.vector_table:
        if binding.embedding_dim is not None and binding.embedding_dim != query_embedding_dim:
            return None
        if vector_table_exists(connection, binding.vector_table):
            table_dim = get_vector_table_dim(connection, binding.vector_table)
            if table_dim is None or table_dim == query_embedding_dim:
                return binding.vector_table

    table_name = get_legacy_vector_table_name()
    if not vector_table_exists(connection, table_name):
        return None
    if _count_embeddings_for_chunk_ids(
        connection,
        table_name=table_name,
        chunk_ids=[
            chunk_id
            for chunk_id in session.exec(
                select(RetrievalChunk.id).where(RetrievalChunk.subject == subject)
            ).all()
            if chunk_id is not None
        ],
    ) <= 0:
        return None
    table_dim = get_vector_table_dim(connection, table_name)
    if table_dim is not None and table_dim != query_embedding_dim:
        return None
    return table_name


def update_chunk_vector_metadata(
    session: Session,
    *,
    subject: str,
    chunk_ids: list[int],
    embedding_model: str | None,
    vector_ref: str | None,
) -> None:
    if not chunk_ids:
        return

    statement = select(RetrievalChunk).where(
        RetrievalChunk.subject == subject,
        RetrievalChunk.id.in_(chunk_ids),
    )
    chunks = list(session.exec(statement).all())
    for chunk in chunks:
        chunk.embedding_model = embedding_model
        chunk.vector_ref = vector_ref
        chunk.updated_at = utcnow()
        session.add(chunk)
    session.commit()


def bulk_insert_embeddings(
    session: Session,
    *,
    subject: str,
    chunk_ids: list[int],
    embeddings: list[list[float]],
    embedding_model: str | None = None,
) -> None:
    if not is_vec_ready():
        logger.warning("bulk_insert_embeddings_skipped", reason="vector extension unavailable", subject=subject)
        return
    if not chunk_ids or not embeddings:
        return
    if len(chunk_ids) != len(embeddings):
        raise ValueError(
            "chunk_ids and embeddings must have the same length. "
            f"Got {len(chunk_ids)} chunk_ids and {len(embeddings)} embeddings."
        )

    if is_postgres():
        _pg_bulk_insert_embeddings(session, subject=subject, chunk_ids=chunk_ids, embeddings=embeddings, embedding_model=embedding_model)
    else:
        _sqlite_bulk_insert_embeddings(session, subject=subject, chunk_ids=chunk_ids, embeddings=embeddings, embedding_model=embedding_model)


def _pg_bulk_insert_embeddings(
    session: Session,
    *,
    subject: str,
    chunk_ids: list[int],
    embeddings: list[list[float]],
    embedding_model: str | None = None,
) -> None:
    """pgvector：直接更新 retrieval_chunk.embedding 列。"""

    runtime_model = embedding_model or get_settings().normalized_embedding_model
    try:
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            session.execute(
                sa.text(
                    "UPDATE retrieval_chunk SET embedding = :emb::vector "
                    "WHERE id = :cid"
                ),
                {"cid": chunk_id, "emb": str(embedding)},
            )
        session.commit()
        update_chunk_vector_metadata(
            session,
            subject=subject,
            chunk_ids=chunk_ids,
            embedding_model=runtime_model,
            vector_ref="retrieval_chunk.embedding",
        )
        logger.info(
            "bulk_insert_embeddings_completed",
            subject=subject,
            chunk_count=len(chunk_ids),
            embedding_dim=len(embeddings[0]) if embeddings else 0,
            backend="pgvector",
        )
    except Exception:
        session.rollback()
        logger.exception(
            "bulk_insert_embeddings_failed",
            subject=subject,
            chunk_count=len(chunk_ids),
            backend="pgvector",
        )
        raise


def _sqlite_bulk_insert_embeddings(
    session: Session,
    *,
    subject: str,
    chunk_ids: list[int],
    embeddings: list[list[float]],
    embedding_model: str | None = None,
) -> None:
    """sqlite-vec：写入 vec0 虚拟表。"""

    table_name = _resolve_insert_table(
        session,
        subject=subject,
        embedding_dim=len(embeddings[0]),
    )
    if table_name is None:
        logger.info("bulk_insert_embeddings_skipped", subject=subject, reason="subject_vectors_disabled")
        return

    connection = session.connection()
    quoted_table_name = quote_sqlite_identifier(table_name)
    runtime_model = embedding_model or get_settings().normalized_embedding_model
    try:
        _delete_embeddings_from_table(connection, table_name=table_name, chunk_ids=chunk_ids)
        legacy_table = _legacy_table_for_subject(session, subject=subject, chunk_ids=chunk_ids)
        if legacy_table is not None:
            _delete_embeddings_from_table(connection, table_name=legacy_table, chunk_ids=chunk_ids)
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            connection.execute(
                sa.text(
                    f"INSERT INTO {quoted_table_name}(chunk_id, embedding) "
                    "VALUES (:chunk_id, :embedding)"
                ),
                {"chunk_id": chunk_id, "embedding": str(embedding)},
            )
        session.commit()
        update_chunk_vector_metadata(
            session,
            subject=subject,
            chunk_ids=chunk_ids,
            embedding_model=runtime_model,
            vector_ref=table_name,
        )
        logger.info(
            "bulk_insert_embeddings_completed",
            subject=subject,
            chunk_count=len(chunk_ids),
            embedding_dim=len(embeddings[0]) if embeddings else 0,
            table_name=table_name,
        )
    except Exception:
        session.rollback()
        logger.exception(
            "bulk_insert_embeddings_failed",
            subject=subject,
            chunk_count=len(chunk_ids),
            embedding_dim=len(embeddings[0]) if embeddings else 0,
            chunk_ids_preview=chunk_ids[:5],
            table_name=table_name,
        )
        raise


def delete_embeddings_by_chunk_ids(
    session: Session,
    *,
    subject: str,
    chunk_ids: list[int],
) -> None:
    if not chunk_ids or not is_vec_ready():
        return

    if is_postgres():
        # pgvector：将 embedding 列置 NULL
        placeholders = ", ".join(f":cid_{i}" for i in range(len(chunk_ids)))
        params = {f"cid_{i}": cid for i, cid in enumerate(chunk_ids)}
        try:
            session.execute(
                sa.text(f"UPDATE retrieval_chunk SET embedding = NULL WHERE id IN ({placeholders})"),
                params,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        return

    # SQLite：从 vec0 虚拟表中删除
    connection = session.connection()
    binding = _get_subject_binding(session, subject)
    table_names = [get_legacy_vector_table_name()]
    if binding is not None and binding.vector_table:
        table_names.append(binding.vector_table)
    else:
        table_names.append(build_subject_vector_table_name(subject))

    try:
        for table_name in dict.fromkeys(table_names):
            _delete_embeddings_from_table(connection, table_name=table_name, chunk_ids=chunk_ids)
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
        logger.warning("vector_search_skipped", reason="vector extension unavailable", subject=subject)
        return []
    if top_k <= 0 or not query_embedding:
        return []

    if is_postgres():
        return _pg_vector_search(session, query_embedding, subject, top_k=top_k)
    return _sqlite_vector_search(session, query_embedding, subject, top_k=top_k)


def _pg_vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    """pgvector 余弦相似度检索。"""

    rows = session.execute(
        sa.text(
            """
            SELECT id, 1 - (embedding <=> :query_emb::vector) AS score
            FROM retrieval_chunk
            WHERE subject = :subject
              AND is_active = true
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_emb::vector
            LIMIT :top_k
            """
        ),
        {
            "subject": subject,
            "query_emb": str(query_embedding),
            "top_k": top_k,
        },
    ).fetchall()

    results: list[ChunkSearchResult] = []
    for row in rows:
        chunk = session.get(RetrievalChunk, row[0])
        if chunk is None:
            continue
        results.append(ChunkSearchResult(chunk=chunk, score=float(row[1])))
    return results


def _sqlite_vector_search(
    session: Session,
    query_embedding: list[float],
    subject: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    """sqlite-vec MATCH 检索。"""

    table_name = _resolve_search_table(
        session,
        subject=subject,
        query_embedding_dim=len(query_embedding),
    )
    if table_name is None:
        logger.info("vector_search_skipped", subject=subject, reason="subject_vectors_unavailable")
        return []

    connection = session.connection()
    quoted_table_name = quote_sqlite_identifier(table_name)
    rows = connection.execute(
        sa.text(
            f"""
            SELECT
                ce.chunk_id,
                ce.distance
            FROM {quoted_table_name} ce
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
