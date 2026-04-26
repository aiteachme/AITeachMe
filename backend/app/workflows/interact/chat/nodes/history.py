"""History-loading node builders for the interact workflow.

Reads DB: ``chat_message`` plus active mastery/attempt summaries.
Writes DB: none.
Writes FS: none.
Idempotency: read-only node; repeated runs return the latest persisted history snapshot.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session

from app.shared.infra.settings import get_settings
from app.shared.infra.database import managed_session
from app.repositories import profile_repo, subject_repo
from app.repositories.chats_repo import get_recent_turns
from app.utils.presenters import mastery_to_text
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.profile.pipeline.lib.subject_profile import build_subject_profile_summary
from app.workflows.interact.chat.state import InteractWorkflowState
from app.workflows.interact.chat.lib.types import (
    MistakeSummary,
    RecentMessage,
    SubjectContextSummary,
    WeakPointSummary,
)


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


def build_load_history_state_node(*, context: WorkflowContext, session: Session | None = None):
    """Build the node that loads history, weak points, and recent mistakes."""

    settings = get_settings()
    workflow_logger = context.get_logger()

    def load_history_state(state: InteractWorkflowState) -> InteractWorkflowState:
        with _node_session(session) as db_session:
            recent_messages = [
                RecentMessage(role=item.role, content=item.content)
                for item in get_recent_turns(
                    db_session,
                    state["subject"],
                    user_id=state["user_id"],
                    n_turns=settings.interact.history_turns,
                    session_id=state.get("session_id"),
                )
            ]
            weak_points_from_mastery = profile_repo.list_weak_knowledge_unit_summaries(
                db_session,
                user_id=state["user_id"],
                subject=state["subject"],
                limit=10,
            )
            weak_points = [
                WeakPointSummary(
                    knowledge_point=name,
                    mastery_text=mastery_to_text(mastery),
                )
                for name, mastery in weak_points_from_mastery
            ]

            recent_mistakes_raw = profile_repo.list_recent_wrong_attempt_summaries(
                db_session,
                user_id=state["user_id"],
                subject=state["subject"],
                limit=5,
            )
            recent_mistakes = [MistakeSummary.model_validate(item) for item in recent_mistakes_raw]
            subject_context = _load_subject_context(
                db_session,
                subject=state["subject"],
                user_id=state["user_id"],
            )
        workflow_logger.info(
            "interact_history_loaded",
            recent_message_count=len(recent_messages),
            weak_point_count=len(weak_points),
            recent_mistake_count=len(recent_mistakes),
            subject_name=subject_context.subject_name,
        )
        return {
            **state,
            "recent_messages": recent_messages,
            "subject_context": subject_context,
            "weak_points": weak_points,
            "recent_mistakes": recent_mistakes,
        }

    return load_history_state


def _load_subject_context(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> SubjectContextSummary:
    record = subject_repo.get_subject_by_slug(session, subject, owner_user_id=user_id)
    if record is None:
        record = subject_repo.get_subject_by_slug(session, subject)

    try:
        profile = build_subject_profile_summary(session, subject=subject, user_id=user_id)
    except Exception:
        profile = None

    return SubjectContextSummary(
        subject_id=subject,
        subject_name=(record.name if record and record.name else subject),
        description=record.description if record else "",
        user_intent=record.user_intent if record else "",
        learning_intent=record.learning_intent_text if record else "",
        subject_intro=record.subject_intro_text if record else "",
        llm_context=record.llm_context_text if record else "",
        discipline=record.detected_discipline if record else None,
        sub_discipline=record.detected_sub_discipline if record else None,
        avg_mastery=profile.avg_mastery if profile else None,
        weak_knowledge_unit_count=profile.weak_knowledge_unit_count if profile else None,
        pending_review_count=profile.pending_review_count if profile else None,
        due_review_count=profile.due_review_count if profile else None,
        difficulty_focus=profile.difficulty_focus if profile else None,
        recommended_question_types=profile.recommended_question_types if profile else [],
        recommended_exam_mode=profile.recommended_exam_mode if profile else None,
    )
