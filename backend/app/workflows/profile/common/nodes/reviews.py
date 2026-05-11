"""Profile review scheduling node.

This node converts updated mastery state ids into pending review fields. It
does not decide exam generation or frontend study-plan rendering.
"""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.profile.common.lib.reviews import schedule_reviews
from app.workflows.profile.common.nodes.sessioning import node_session
from app.workflows.profile.common.state import ProfileWorkflowState


def build_schedule_reviews_node(*, session: Session | None = None):
    """Build the review scheduler node for the exam-driven update lane."""

    def schedule_reviews_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        user_id = state.get("user_id")
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with node_session(session) as db_session:
                review_tasks = schedule_reviews(
                    db_session,
                    user_id=user_id,
                    course_id=course_id,
                    updated_state_ids=list(state.get("updated_state_ids", [])),
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"schedule_reviews_failed:{exc}",
            }
        return {
            **state,
            "review_task_ids": [int(task.id) for task in review_tasks if task.id is not None],
            "review_scheduled": True,
            "error": None,
        }

    return schedule_reviews_node


__all__ = ["build_schedule_reviews_node"]
