"""Retrieval helpers for the interact workflow.

Uses the LlamaIndex adapter layer to retrieve knowledge chunks,
replacing the previous hand-written RetrievalPipeline.
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.shared.infra.search import search_knowledge
from app.shared.infra.subject import get_subject_vector_search_notice
from app.workflows.interact.support.types import RetrievedContext

logger = structlog.get_logger(__name__)


async def retrieve_context(
    *,
    session: Session,
    query: str,
    subject: str,
    top_k: int,
    similarity_threshold: float,
) -> list[RetrievedContext]:
    """Retrieve prompt-ready context chunks for one chat question.

    This function uses the LlamaIndex-managed subject index.
    """

    normalized_query = query.strip()
    if not normalized_query or top_k <= 0:
        return []

    # Check if vector search is available for this subject
    search_notice = get_subject_vector_search_notice(session, subject_slug=subject)
    if search_notice is not None:
        logger.info(
            "interact_retrieval_skipped",
            subject=subject,
            reason=search_notice,
        )
        return []

    chunks = await search_knowledge(normalized_query, subject, top_k=top_k)

    results: list[RetrievedContext] = []
    for chunk in chunks:
        score = float(chunk.score)
        # Filter by strict minimum threshold
        if score < similarity_threshold:
            continue

        results.append(
            RetrievedContext(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                title=chunk.title,
                header_path=chunk.header_path,
                content=chunk.content,
                score=score,
                low_relevance=score < similarity_threshold * 1.5,
            )
        )

    logger.info(
        "interact_retrieval_done",
        subject=subject,
        query_len=len(normalized_query),
        node_count=len(chunks),
        result_count=len(results),
    )
    return results


__all__ = ["retrieve_context"]
