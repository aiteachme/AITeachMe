"""Retrieval helpers for the interact workflow.

Uses the LlamaIndex adapter layer to retrieve knowledge chunks,
replacing the previous hand-written RetrievalPipeline.
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.shared.infra.config import get_settings
from app.shared.infra.subject import get_subject_vector_search_notice
from app.shared.infra.search.llamaindex_adapter import build_knowledge_retriever
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

    This function uses the LlamaIndex-based retriever which internally
    bridges to the same sqlite-vec / pgvector storage.
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

    retriever = build_knowledge_retriever(subject=subject, top_k=top_k)
    nodes = await retriever.aretrieve(normalized_query)

    results: list[RetrievedContext] = []
    for node_with_score in nodes:
        node = node_with_score.node
        score = node_with_score.score or 0.0
        metadata = node.metadata or {}

        # Filter by strict minimum threshold
        if score < similarity_threshold:
            continue

        results.append(
            RetrievedContext(
                chunk_id=int(metadata.get("chunk_id", 0)),
                document_id=int(metadata.get("document_id", 0)),
                title=str(metadata.get("title", "")),
                header_path=str(metadata.get("header_path", "")),
                content=node.get_content(),
                score=score,
                low_relevance=score < similarity_threshold * 1.5,
            )
        )

    logger.info(
        "interact_retrieval_done",
        subject=subject,
        query_len=len(normalized_query),
        node_count=len(nodes),
        result_count=len(results),
    )
    return results


__all__ = ["retrieve_context"]
