"""LlamaIndex ingestion primitives used by the course vector index.

The application still owns business identities such as RawFile IDs,
digest_chunk_uid, header paths and page hints. This module centralizes the
RAG-specific primitives that can safely be delegated to LlamaIndex:
text splitting and embedding through the project's LlamaIndex adapter.
"""

from __future__ import annotations

import structlog
from llama_index.core.node_parser import SentenceSplitter

from app.shared.infra.embedding import ATMEmbedding

logger = structlog.get_logger(__name__)

DEFAULT_INGESTION_CHUNK_SIZE = 768
DEFAULT_INGESTION_CHUNK_OVERLAP = 80


def build_text_splitter(
    *,
    chunk_size: int = DEFAULT_INGESTION_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_INGESTION_CHUNK_OVERLAP,
) -> SentenceSplitter:
    """Build the LlamaIndex splitter used for canonical retrieval chunks."""

    resolved_chunk_size = max(128, int(chunk_size))
    resolved_overlap = max(0, min(int(chunk_overlap), resolved_chunk_size // 2))
    return SentenceSplitter.from_defaults(
        chunk_size=resolved_chunk_size,
        chunk_overlap=resolved_overlap,
        include_metadata=False,
        include_prev_next_rel=False,
    )


def split_text_for_ingestion(
    text: str,
    *,
    chunk_size: int = DEFAULT_INGESTION_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_INGESTION_CHUNK_OVERLAP,
) -> list[str]:
    """Split text with LlamaIndex while returning plain text chunks."""

    normalized = str(text or "").strip()
    if not normalized:
        return []

    splitter = build_text_splitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = [chunk.strip() for chunk in splitter.split_text(normalized) if chunk.strip()]
    return chunks or [normalized]


async def aembed_texts_for_ingestion(
    texts: list[str],
    *,
    model: str | None = None,
    soft_fail: bool = False,
) -> list[list[float]]:
    """Embed texts through LlamaIndex's BaseEmbedding interface."""

    payloads = [str(text or "").strip() for text in texts]
    if not payloads or any(not text for text in payloads):
        return []

    try:
        embed_model = ATMEmbedding(model_name=model)
        embeddings = await embed_model.aget_text_embedding_batch(payloads)
    except Exception as exc:
        if soft_fail:
            logger.warning(
                "llamaindex_ingestion_embedding_soft_failed",
                model=model,
                text_count=len(payloads),
                error=str(exc),
            )
            return []
        raise
    if len(embeddings) != len(payloads):
        message = (
            "LlamaIndex embedding returned an unexpected vector count. "
            f"expected={len(payloads)} actual={len(embeddings)}"
        )
        if soft_fail:
            logger.warning(
                "llamaindex_ingestion_embedding_count_mismatch",
                model=model,
                text_count=len(payloads),
                embedding_count=len(embeddings),
            )
            return []
        raise RuntimeError(message)
    return embeddings


__all__ = [
    "DEFAULT_INGESTION_CHUNK_OVERLAP",
    "DEFAULT_INGESTION_CHUNK_SIZE",
    "aembed_texts_for_ingestion",
    "build_text_splitter",
    "split_text_for_ingestion",
]
