"""Public search helpers used by planner and docgen.

The ``search_knowledge()`` function now uses the LlamaIndex adapter layer
internally, while keeping the same public API contract.
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.shared.infra.config import get_settings
from app.shared.infra.database import get_engine
from app.shared.infra.search.knowledge import RetrievedChunk
from app.shared.infra.search.llamaindex_adapter import build_knowledge_retriever
from app.shared.infra.search.types import SearchResult
from app.shared.infra.subject import get_subject_vector_search_notice
from app.shared.infra.search.web import dispatch_web_search

logger = structlog.get_logger(__name__)


async def web_search(
    query: str,
    *,
    top_k: int = 5,
    subject: str | None = None,
    local_sections: list[object] | None = None,
) -> list[SearchResult]:
    return await dispatch_web_search(
        query,
        top_k=top_k,
        subject=subject,
        local_sections=local_sections,
    )


async def get_knowledge_search_notice(subject_id: str) -> str | None:
    normalized_subject = subject_id.strip()
    if not normalized_subject:
        return None

    engine = get_engine()
    with Session(engine) as session:
        return get_subject_vector_search_notice(session, subject_slug=normalized_subject)


async def search_knowledge(
    query: str,
    subject_id: str,
    *,
    top_k: int = 5,
    enable_rerank: bool = True,
) -> list[RetrievedChunk]:
    """Search the local knowledge base using the LlamaIndex retriever.

    This replaces the previous hand-written embed → vector_search → rerank
    pipeline with the LlamaIndex adapter layer while keeping the same
    return type (``list[RetrievedChunk]``).
    """

    normalized_query = query.strip()
    normalized_subject = subject_id.strip()
    if not normalized_query or not normalized_subject or top_k <= 0:
        return []

    search_notice = await get_knowledge_search_notice(normalized_subject)
    if search_notice is not None:
        logger.info("knowledge_search_skipped", subject=normalized_subject, reason=search_notice)
        return []

    settings = get_settings()
    should_rerank = enable_rerank and bool(settings.rag_rerank_model)

    try:
        retriever = build_knowledge_retriever(
            subject=normalized_subject,
            top_k=top_k,
            enable_rerank=should_rerank,
        )
        nodes = await retriever.aretrieve(normalized_query)
    except Exception as exc:
        logger.warning("search_knowledge_failed", subject=normalized_subject, error=str(exc))
        return []

    # Convert LlamaIndex nodes back to RetrievedChunk
    chunks: list[RetrievedChunk] = []
    for node_with_score in nodes:
        node = node_with_score.node
        metadata = node.metadata or {}
        chunks.append(
            RetrievedChunk(
                chunk_id=int(metadata.get("chunk_id", 0)),
                document_id=int(metadata.get("document_id", 0)),
                title=str(metadata.get("title", "")),
                header_path=str(metadata.get("header_path", "")),
                content=node.get_content(),
                score=node_with_score.score or 0.0,
                source=str(metadata.get("source", "vector")),
            )
        )

    result = chunks[:top_k]
    logger.info(
        "knowledge_search_complete",
        subject=normalized_subject,
        query_len=len(normalized_query),
        result_count=len(result),
    )
    return result


__all__ = ["get_knowledge_search_notice", "search_knowledge", "web_search"]
