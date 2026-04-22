"""Public search helpers used by planner and docgen.

The ``search_knowledge()`` function uses the LlamaIndex-managed subject
index internally, while keeping the same public API contract.
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.shared.infra.settings import get_settings
from app.shared.infra.database import get_engine
from app.repositories.knowledge.knowledge_repo import get_chunk_by_id
from app.shared.infra.search.knowledge import RetrievedChunk
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
    """Search candidate sources for workflow code.

    This is the public, workflow-facing wrapper around the lower-level
    ``dispatch_web_search`` scheduler. Most call sites should use this helper
    instead of importing ``search.web`` directly.

    Args:
        query: Natural-language search query.
        top_k: Maximum number of final fused results to return.
        subject: Optional subject slug. When present, ``local_rag`` may search
            the subject's indexed uploaded materials before external providers.
        local_sections: Optional in-memory local sections. This is for planner
            and draft contexts that have not necessarily been indexed yet.

    Returns:
        Ranked candidate sources as normalized ``SearchResult`` objects.
    """

    return await dispatch_web_search(
        query,
        top_k=top_k,
        subject=subject,
        local_sections=local_sections,
    )


async def get_knowledge_search_notice(subject_id: str) -> str | None:
    """Return a human-readable reason when subject vector search is unavailable.

    ``None`` means local vector search can be attempted. Non-``None`` values are
    logged by callers and usually mean the subject has no ready vector index, is
    still building, or has incompatible vector settings.
    """

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
    """Search the local subject knowledge base.

    This function is deliberately narrower than ``web_search``: it only queries
    uploaded/ingested materials for one subject. It uses the LlamaIndex-managed
    subject index, then rehydrates database chunks so callers receive stable
    ``RetrievedChunk`` records rather than raw vector-store nodes.

    Args:
        query: User/query text to search for.
        subject_id: Subject slug whose indexed materials should be searched.
        top_k: Maximum number of chunks to return after optional rerank.
        enable_rerank: Whether to apply the configured rerank model when
            ``settings.models.rerank`` is set.

    Returns:
        Retrieved local chunks. Empty list means unavailable index, invalid
        input, no hits, or provider failure; failures are logged and do not
        raise into workflow code.
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
    should_rerank = enable_rerank and settings.rerank_configured

    try:
        from app.shared.infra.search.llamaindex_index import retrieve_subject_chunks

        hits = await retrieve_subject_chunks(
            normalized_subject,
            normalized_query,
            top_k=top_k * 3 if should_rerank else top_k,
        )
    except Exception as exc:
        logger.warning("search_knowledge_failed", subject=normalized_subject, error=str(exc))
        return []

    chunks: list[RetrievedChunk] = []
    with Session(get_engine()) as session:
        for hit in hits:
            chunk = get_chunk_by_id(session, hit.chunk_id)
            if chunk is None or chunk.subject != normalized_subject:
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=int(chunk.id or 0),
                    document_id=int(chunk.document_id),
                    title=chunk.title,
                    header_path=chunk.header_path,
                    content=chunk.content,
                    score=float(hit.score),
                    source=hit.source,
                )
            )

    if should_rerank:
        from app.shared.infra.search.knowledge import rerank_chunks

        chunks = await rerank_chunks(normalized_query, chunks, top_k=top_k)

    result = chunks[:top_k]
    logger.info(
        "knowledge_search_complete",
        subject=normalized_subject,
        query_len=len(normalized_query),
        result_count=len(result),
    )
    return result


__all__ = ["get_knowledge_search_notice", "search_knowledge", "web_search"]
