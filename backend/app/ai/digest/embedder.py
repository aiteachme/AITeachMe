"""
批量嵌入节点

通过 core/embedding.py 批量计算嵌入向量。
写入 Chunk 表和 chunk_embeddings 虚拟表。
更新 Knowledge.pipeline_stage 为 embedded。

需求：7.6, 7.7
"""

from __future__ import annotations

import structlog

from app.core.embedding import aembed_texts
from app.ai.digest.chunker import ChunkData
from app.repositories.models import Chunk

logger = structlog.get_logger()


async def embed_chunks(chunks: list[ChunkData]) -> list[list[float]]:
    """批量计算 chunk 嵌入向量。

    将每个 chunk 的 title + content 拼接作为嵌入输入文本。

    Args:
        chunks: 分块数据列表。

    Returns:
        与 chunks 等长的嵌入向量列表。

    Raises:
        LLMCallError: embedding 调用失败时抛出。
    """
    if not chunks:
        return []

    # 拼接 title 和 content 作为嵌入文本
    texts = []
    for chunk in chunks:
        text = chunk.title
        if chunk.content:
            text = f"{chunk.title}\n{chunk.content}"
        texts.append(text)

    embeddings = await aembed_texts(texts)
    logger.info("chunks_embedded", num_chunks=len(chunks), dim=len(embeddings[0]) if embeddings else 0)
    return embeddings


def save_chunks_and_embeddings(
    session: "Session",
    knowledge_id: int,
    chunks: list[ChunkData],
    embeddings: list[list[float]],
) -> list[Chunk]:
    """将分块数据和嵌入向量写入数据库。

    写入 Chunk 表记录，然后批量插入 embedding 到 chunk_embeddings 虚拟表。

    Args:
        session: 数据库会话。
        knowledge_id: 关联的 Knowledge ID。
        chunks: 分块数据列表。
        embeddings: 对应的嵌入向量列表。

    Returns:
        已插入的 Chunk 记录列表。
    """
    from app.repositories.knowledge_repo import bulk_create_chunks, bulk_insert_embeddings

    # 创建 Chunk 记录
    db_chunks = [
        Chunk(
            knowledge_id=knowledge_id,
            title=c.title,
            level=c.level,
            header_path=c.header_path,
            chunk_index=c.chunk_index,
            content=c.content,
        )
        for c in chunks
    ]
    db_chunks = bulk_create_chunks(session, db_chunks)

    # 批量插入 embedding
    chunk_ids = [c.id for c in db_chunks]
    bulk_insert_embeddings(session, chunk_ids, embeddings)

    logger.info(
        "chunks_and_embeddings_saved",
        knowledge_id=knowledge_id,
        num_chunks=len(db_chunks),
    )
    return db_chunks
