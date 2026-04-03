"""Retrieval node builders for the interact workflow.

Reads DB: ``retrieval_chunk`` and subject-scoped vector tables through the retrieval pipeline.
Writes DB: none.
Writes FS: none.
Idempotency: read-only retrieval for one question / subject pair.
"""

from __future__ import annotations

from sqlmodel import Session

from app.core.config import get_settings
from app.services.subject_embedding_service import get_subject_vector_search_notice
from app.workflows.common.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.retrieval import retrieve_context


def build_retrieve_context_node(*, context: WorkflowContext, session: Session):
    """Build the node that retrieves supporting chunks for one question."""

    settings = get_settings()
    workflow_logger = context.get_logger()

    async def retrieve_context_node(state: InteractWorkflowState) -> InteractWorkflowState:
        search_notice = get_subject_vector_search_notice(
            session,
            subject_slug=state["subject"],
        )
        has_explicit_context = bool(state.get("selected_context") or state.get("source_chunk_id"))
        if search_notice is not None and not has_explicit_context:
            workflow_logger.info(
                "interact_context_skipped",
                subject=state["subject"],
                reason=search_notice,
            )
            return {
                **state,
                "retrieval_results": [],
                "contexts": None,
                "error": search_notice,
            }
        if search_notice is not None:
            workflow_logger.info(
                "interact_context_degraded",
                subject=state["subject"],
                reason=search_notice,
            )
            return {
                **state,
                "retrieval_results": [],
                "contexts": None,
            }

        retrieval_results = await retrieve_context(
            session=session,
            query=state["question"],
            subject=state["subject"],
            top_k=settings.rag_top_k,
            similarity_threshold=settings.rag_similarity_threshold,
        )
        contexts = [item.to_context_item() for item in retrieval_results] or None
        workflow_logger.info(
            "interact_context_retrieved",
            retrieval_count=len(retrieval_results),
            citation_count=len(contexts or []),
        )
        return {
            **state,
            "retrieval_results": retrieval_results,
            "contexts": contexts,
        }

    return retrieve_context_node
