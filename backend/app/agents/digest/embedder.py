"""Embedding generation and persistence for digest chunks."""

from __future__ import annotations

import structlog

from app.agents.digest.chunker import ChunkData
from app.core.embedding import aembed_texts
from app.repositories.models import DocumentChunk

logger = structlog.get_logger()


async def embed_chunks(chunks: list[ChunkData]) -> list[list[float]]:
    if not chunks:
        return []

    texts = []
    for chunk in chunks:
        text = chunk.title
        if chunk.content:
            text = f"{chunk.title}\n{chunk.content}"
        texts.append(text)

    embeddings = await aembed_texts(texts)
    logger.info(
        "chunks_embedded",
        num_chunks=len(chunks),
        embedding_dim=len(embeddings[0]) if embeddings else 0,
    )
    return embeddings


def save_chunks_and_embeddings(
    session: "Session",
    document_id: int,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
) -> list[DocumentChunk]:
    from app.repositories.knowledge_repo import bulk_create_chunks, bulk_insert_embeddings

    db_chunks = [
        DocumentChunk(
            document_id=document_id,
            title=chunk.title,
            level=chunk.level,
            header_path=chunk.header_path,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
        )
        for chunk in chunks
    ]
    db_chunks = bulk_create_chunks(session, db_chunks)
    bulk_insert_embeddings(session, [chunk.id for chunk in db_chunks if chunk.id is not None], embeddings)

    logger.info(
        "chunks_and_embeddings_saved",
        document_id=document_id,
        num_chunks=len(db_chunks),
    )
    return db_chunks
