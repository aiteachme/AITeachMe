"""切块向量化。"""

from __future__ import annotations

import structlog

from app.workflows.digest.knowledge_graph.services.chunker import ChunkData
from app.shared.infra.embedding import aembed_texts

logger = structlog.get_logger()


async def embed_chunks(chunks: list[ChunkData]) -> list[list[float]]:
    """为切块生成向量。"""

    if not chunks:
        return []

    texts = [
        f"{chunk.title}\n{chunk.content}".strip()
        for chunk in chunks
    ]
    embeddings = await aembed_texts(texts)
    logger.info(
        "embed_chunks_complete",
        chunk_count=len(chunks),
        embedding_dim=len(embeddings[0]) if embeddings else 0,
    )
    return embeddings

