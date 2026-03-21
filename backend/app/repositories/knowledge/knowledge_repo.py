"""知识文档数据访问层。"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
import structlog
from sqlmodel import Session, func, select

from app.core.database import require_vec_ready
from app.models import (
    Document,
    DocumentChunk,
)
from app.utils.time import utcnow

logger = structlog.get_logger()


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
    """更新文档处理步骤。"""

    document = session.get(Document, document_id)
    if document is None:
        return None
    document.current_step = current_step
    document.updated_at = utcnow()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


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


def bulk_insert_embeddings(
    session: Session,
    chunk_ids: list[int],
    embeddings: list[list[float]],
) -> None:
    """批量写入向量表。"""

    require_vec_ready()
    if not chunk_ids or not embeddings:
        return
    if len(chunk_ids) != len(embeddings):
        raise ValueError(
            "chunk_ids and embeddings must have the same length. "
            f"Got {len(chunk_ids)} chunk_ids and {len(embeddings)} embeddings."
        )

    conn = session.connection()
    try:
        params = {f"chunk_id_{index}": value for index, value in enumerate(chunk_ids)}
        placeholders = ", ".join(f":chunk_id_{index}" for index in range(len(chunk_ids)))
        conn.execute(
            sa.text(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})"),
            params,
        )
        for chunk_id, embedding in zip(chunk_ids, embeddings):
            conn.execute(
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
    if top_k <= 0:
        return []

    conn = session.connection()
    try:
        rows = conn.execute(
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
    except Exception:
        logger.exception(
            "vector_search_failed",
            subject=subject,
            top_k=top_k,
            embedding_dim=len(query_embedding),
        )
        raise

    results: list[ChunkSearchResult] = []
    for row in rows:
        chunk = session.get(DocumentChunk, row[0])
        if chunk is None:
            continue
        distance = row[1]
        score = 1.0 / (1.0 + distance) if distance >= 0 else 0.0
        results.append(ChunkSearchResult(chunk=chunk, score=score))
    return results
