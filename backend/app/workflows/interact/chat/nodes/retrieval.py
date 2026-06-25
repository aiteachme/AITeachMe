"""Retrieval node builders for the interact workflow.

Reads DB: KnowledgeUnit/KG/evidence tables and course-scoped vector tables as fallback.
Writes DB: none.
Writes FS: none.
Idempotency: read-only retrieval for one question / course pair.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session

from app.shared.infra.settings import get_settings
from app.shared.infra.database import managed_session
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.state import InteractWorkflowState
from app.workflows.interact.chat.lib.intent import has_entry_context, should_use_course_grounding
from app.workflows.interact.chat.lib.retrieval import retrieve_context


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


def build_retrieve_context_node(*, context: WorkflowContext, session: Session | None = None):
    """Build the node that retrieves supporting chunks for one question."""

    settings = get_settings()
    workflow_logger = context.get_logger()

    async def retrieve_context_node(state: InteractWorkflowState) -> InteractWorkflowState:
        has_primary_context = has_entry_context(
            selected_context=state.get("selected_context"),
            selection_context=state.get("selection_context"),
        )
        attached_file_ids = list(state.get("attached_file_ids") or [])
        if not should_use_course_grounding(
            question=state["question"],
            scene=state.get("scene"),
            source=state.get("source"),
            has_primary_context=has_primary_context,
        ):
            workflow_logger.info(
                "interact_context_retrieval_skipped",
                reason="ordinary_chat_without_course_intent",
            )
            return {
                **state,
                "retrieval_results": [],
                "contexts": None,
            }

        with _node_session(session) as db_session:
            retrieval_results = await retrieve_context(
                session=db_session,
                query=_build_retrieval_query(
                    question=state["question"],
                    selected_context=state.get("selected_context"),
                    selection_context=state.get("selection_context"),
                ),
                course_id=state["course_id"],
                top_k=settings.rag.top_k,
                similarity_threshold=settings.rag.similarity_threshold,
                user_id=state["user_id"],
                attached_file_ids=attached_file_ids,
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


def _build_retrieval_query(
    *,
    question: str,
    selected_context: str | None,
    selection_context: object | None,
) -> str:
    selected = (selected_context or _selected_context_fallback(selection_context)).strip()
    if not selected:
        return question
    clipped = selected[:1200]
    return f"{question}\n\n用户划选内容：{clipped}"


def _selected_context_fallback(selection_context: object | None) -> str:
    if selection_context is None:
        return ""
    values = [
        getattr(selection_context, "selected_text", None),
        getattr(selection_context, "anchor_title", None),
        getattr(selection_context, "section_title", None),
        getattr(selection_context, "section_excerpt", None),
    ]
    return "\n".join(str(value).strip() for value in values if str(value or "").strip())
