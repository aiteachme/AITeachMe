"""Repository helpers for retrieval chunks and embeddings."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlmodel import Session, select

from app.shared.infra.settings import get_settings
from app.shared.infra.subject import (
    build_enabled_binding,
    build_subject_index_ref_for_subject,
    get_subject_embedding_binding,
    set_subject_embedding_binding,
)
from app.models import RawFile, RetrievalChunk, Subject
from app.repositories.files_repo import list_raw_files_by_ids
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


def get_document_by_id(session: Session, file_id: str) -> RawFile | None:
    return session.get(RawFile, file_id)


def get_documents_by_source_file_ids(
    session: Session,
    *,
    subject_id: str,
    source_file_ids: list[str],
) -> list[RawFile]:
    if not source_file_ids:
        return []
    return list_raw_files_by_ids(session, subject_id, source_file_ids)


def update_document_content(
    session: Session,
    file_id: str,
    markdown_content: str,
) -> RawFile | None:
    document = session.get(RawFile, file_id)
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
    file_id: str,
    current_step: str | None,
) -> RawFile | None:
    document = session.get(RawFile, file_id)
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


def get_chunks_by_file_id(session: Session, file_id: str) -> list[RetrievalChunk]:
    statement = (
        select(RetrievalChunk)
        .where(RetrievalChunk.file_id == file_id)
        .order_by(RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_file_ids(session: Session, file_ids: list[str]) -> list[RetrievalChunk]:
    if not file_ids:
        return []
    statement = (
        select(RetrievalChunk)
        .where(RetrievalChunk.file_id.in_(file_ids))
        .order_by(RetrievalChunk.file_id, RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_source_file_ids(
    session: Session,
    *,
    subject_id: str,
    source_file_ids: list[str],
) -> list[RetrievalChunk]:
    if not source_file_ids:
        return []
    statement = (
        select(RetrievalChunk)
        .where(
            RetrievalChunk.subject_id == subject_id,
            RetrievalChunk.file_id.in_(source_file_ids),
        )
        .order_by(RetrievalChunk.file_id, RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunks_by_build_session(session: Session, build_session_id: str) -> list[RetrievalChunk]:
    statement = (
        select(RetrievalChunk)
        .where(RetrievalChunk.build_session_id == build_session_id)
        .order_by(RetrievalChunk.file_id, RetrievalChunk.chunk_index)
    )
    return list(session.exec(statement).all())


def get_chunk_by_id(session: Session, chunk_id: int) -> RetrievalChunk | None:
    return session.get(RetrievalChunk, chunk_id)


def get_chunks_by_ids(session: Session, chunk_ids: list[int]) -> list[RetrievalChunk]:
    if not chunk_ids:
        return []
    statement = select(RetrievalChunk).where(RetrievalChunk.id.in_(chunk_ids))
    return list(session.exec(statement).all())


def delete_chunks_by_file_ids(session: Session, *, subject_id: str, file_ids: list[str]) -> int:
    chunks = get_chunks_by_source_file_ids(
        session,
        subject_id=subject_id,
        source_file_ids=file_ids,
    )
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        delete_embeddings_by_chunk_ids(session, subject_id=subject_id, chunk_ids=chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    session.commit()
    return len(chunks)


def delete_chunks_by_ids(session: Session, *, subject_id: str | None = None, chunk_ids: list[int]) -> int:
    if not chunk_ids:
        return 0
    chunks = [
        chunk
        for chunk_id in chunk_ids
        if (chunk := session.get(RetrievalChunk, chunk_id)) is not None
    ]
    if not chunks:
        return 0
    resolved_subject_id = subject_id or chunks[0].subject_id
    delete_embeddings_by_chunk_ids(
        session,
        subject_id=resolved_subject_id,
        chunk_ids=[chunk.id for chunk in chunks if chunk.id is not None],
    )
    for chunk in chunks:
        session.delete(chunk)
    session.commit()
    return len(chunks)


def delete_documents_by_source_file_ids(
    session: Session,
    *,
    subject_id: str,
    source_file_ids: list[str],
) -> tuple[int, int]:
    documents = get_documents_by_source_file_ids(
        session,
        subject_id=subject_id,
        source_file_ids=source_file_ids,
    )
    chunk_count = delete_chunks_by_file_ids(session, subject_id=subject_id, file_ids=source_file_ids)
    return len(documents), chunk_count


def count_embeddings_for_chunk_ids(
    session: Session,
    *,
    table_name: str,
    chunk_ids: list[int],
) -> int:
    from app.shared.infra.search.llamaindex_index import count_indexed_chunks

    del table_name
    subject_id = _subject_for_chunk_ids(session, chunk_ids)
    if subject_id is None:
        return 0
    return count_indexed_chunks(subject_id, chunk_ids)


def _subject_for_chunk_ids(session: Session, chunk_ids: list[int]) -> str | None:
    if not chunk_ids:
        return None
    statement = select(RetrievalChunk.subject_id).where(RetrievalChunk.id.in_(chunk_ids))
    subjects = [str(item) for item in session.exec(statement).all() if item]
    return subjects[0] if subjects else None


def update_chunk_vector_metadata(
    session: Session,
    *,
    subject_id: str,
    chunk_ids: list[int],
    embedding_model: str | None,
    vector_ref: str | None,
) -> None:
    if not chunk_ids:
        return

    statement = select(RetrievalChunk).where(
        RetrievalChunk.subject_id == subject_id,
        RetrievalChunk.id.in_(chunk_ids),
    )
    chunks = list(session.exec(statement).all())
    for chunk in chunks:
        chunk.embedding_model = embedding_model
        chunk.vector_ref = vector_ref
        chunk.updated_at = utcnow()
        session.add(chunk)
    session.commit()


def clear_chunk_vector_metadata(
    session: Session,
    *,
    subject_id: str,
) -> int:
    """Clear one subject's chunk-level vector metadata and backing embeddings."""

    chunk_ids = [
        chunk_id
        for chunk_id in session.exec(
            select(RetrievalChunk.id).where(RetrievalChunk.subject_id == subject_id)
        ).all()
        if chunk_id is not None
    ]
    if not chunk_ids:
        return 0

    delete_embeddings_by_chunk_ids(session, subject_id=subject_id, chunk_ids=chunk_ids)

    chunks = list(
        session.exec(
            select(RetrievalChunk).where(
                RetrievalChunk.subject_id == subject_id,
                RetrievalChunk.id.in_(chunk_ids),
            )
        ).all()
    )
    for chunk in chunks:
        chunk.embedding_model = None
        chunk.vector_ref = None
        chunk.updated_at = utcnow()
        session.add(chunk)
    session.commit()
    return len(chunks)


def _sync_subject_vector_binding(
    session: Session,
    *,
    subject_id: str,
    embedding_model: str | None,
    embedding_dim: int,
) -> None:
    if not subject_id or not embedding_model or embedding_dim <= 0:
        return

    subject_row = session.exec(select(Subject).where(Subject.id == subject_id)).first()
    if subject_row is None:
        raise RuntimeError(f"Subject `{subject_id}` not found while syncing vector binding.")

    expected_ref = build_subject_index_ref_for_subject(subject_row)
    binding = get_subject_embedding_binding(subject_row)
    if (
        binding is not None
        and binding.mode.value == "enabled"
        and binding.embedding_model == embedding_model
        and binding.embedding_dim == embedding_dim
        and binding.vector_table == expected_ref
    ):
        return

    set_subject_embedding_binding(
        subject_row,
        build_enabled_binding(
            subject_id=subject_id,
            owner_user_id=subject_row.user_id,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
        ),
    )
    subject_row.updated_at = utcnow()
    session.add(subject_row)


def bulk_insert_embeddings(
    session: Session,
    *,
    subject_id: str,
    chunk_ids: list[int],
    embeddings: list[list[float]],
    embedding_model: str | None = None,
) -> None:
    from app.shared.infra.search.llamaindex_index import IndexedChunk, upsert_chunks

    if not chunk_ids or not embeddings:
        return
    if len(chunk_ids) != len(embeddings):
        raise ValueError(
            "chunk_ids and embeddings must have the same length. "
            f"Got {len(chunk_ids)} chunk_ids and {len(embeddings)} embeddings."
        )
    embedding_dim = len(embeddings[0]) if embeddings else 0
    if embedding_dim <= 0:
        raise ValueError("Embeddings must not be empty.")
    for embedding in embeddings[1:]:
        if len(embedding) != embedding_dim:
            raise ValueError(
                "All embeddings must share the same dimension. "
                f"Expected {embedding_dim}, got {len(embedding)}."
            )

    statement = select(RetrievalChunk).where(
        RetrievalChunk.subject_id == subject_id,
        RetrievalChunk.id.in_(chunk_ids),
    )
    chunks = list(session.exec(statement).all())
    chunk_by_id = {int(chunk.id): chunk for chunk in chunks if chunk.id is not None}
    indexed_chunks: list[IndexedChunk] = []
    for chunk_id, embedding in zip(chunk_ids, embeddings, strict=False):
        chunk = chunk_by_id.get(int(chunk_id))
        if chunk is None:
            continue
        indexed_chunks.append(
            IndexedChunk(
                chunk_id=int(chunk.id),
                file_id=chunk.file_id,
                subject_id=chunk.subject_id,
                title=chunk.title,
                header_path=chunk.header_path,
                content=chunk.content,
                digest_chunk_uid=chunk.digest_chunk_uid,
                embedding=embedding,
            )
        )

    if not indexed_chunks:
        return

    upsert_chunks(subject_id, indexed_chunks)
    resolved_embedding_model = embedding_model or get_settings().normalized_embedding_model
    subject_row = session.exec(select(Subject).where(Subject.id == subject_id)).first()
    if subject_row is None:
        raise RuntimeError(f"Subject `{subject_id}` not found while writing embeddings.")

    _sync_subject_vector_binding(
        session,
        subject_id=subject_id,
        embedding_model=resolved_embedding_model,
        embedding_dim=embedding_dim,
    )
    update_chunk_vector_metadata(
        session,
        subject_id=subject_id,
        chunk_ids=[chunk.chunk_id for chunk in indexed_chunks],
        embedding_model=resolved_embedding_model,
        vector_ref=build_subject_index_ref_for_subject(subject_row),
    )
    logger.info(
        "bulk_insert_embeddings_completed",
        subject_id=subject_id,
        chunk_count=len(indexed_chunks),
        embedding_dim=embedding_dim,
        backend="llamaindex",
    )


def delete_embeddings_by_chunk_ids(
    session: Session,
    *,
    subject_id: str,
    chunk_ids: list[int],
) -> None:
    from app.shared.infra.search.llamaindex_index import delete_chunks

    if not chunk_ids:
        return
    delete_chunks(subject_id, chunk_ids)


@dataclass
class ChunkSearchResult:
    """Vector search result item."""

    chunk: RetrievalChunk
    score: float


def vector_search(
    session: Session,
    query_embedding: list[float],
    subject_id: str,
    *,
    top_k: int = 5,
) -> list[ChunkSearchResult]:
    from app.shared.infra.search.llamaindex_index import query_subject_index

    if top_k <= 0 or not query_embedding:
        return []

    hits = query_subject_index(subject_id, query_embedding, top_k=top_k)
    if not hits:
        return []
        
    chunk_ids = [hit.chunk_id for hit in hits]
    chunks = get_chunks_by_ids(session, chunk_ids)
    chunk_by_id = {chunk.id: chunk for chunk in chunks if chunk.id is not None}
    
    results: list[ChunkSearchResult] = []
    for hit in hits:
        chunk = chunk_by_id.get(hit.chunk_id)
        if chunk is None:
            continue
        results.append(ChunkSearchResult(chunk=chunk, score=float(hit.score)))
    return results
