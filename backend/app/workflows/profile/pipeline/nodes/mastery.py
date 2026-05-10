"""Profile mastery update node.

This node applies graded exam results to user knowledge states. It delegates
the scoring math to ``pipeline.lib.mastery`` and only adapts graph state.
"""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.profile.pipeline.lib.mastery import MasteryUpdateResult, update_mastery_from_exam
from app.workflows.profile.pipeline.nodes.sessioning import node_session
from app.workflows.profile.pipeline.state import ProfileWorkflowState


def serialize_mastery_result(result: MasteryUpdateResult) -> dict[str, object]:
    """Convert a mastery update result into LangGraph state."""

    return {
        "exam_paper_id": result.exam_paper_id,
        "states_updated": result.states_updated,
        "updated_state_ids": result.updated_state_ids,
        "already_consumed": result.already_consumed,
    }


def build_update_mastery_node(*, session: Session | None = None):
    """Build the mastery update node used after exam grading."""

    def update_mastery_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        try:
            with node_session(session) as db_session:
                result = update_mastery_from_exam(
                    db_session,
                    state["exam_paper_id"],
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"update_mastery_failed:{exc}",
            }
        return {
            **state,
            "mastery_result": serialize_mastery_result(result),
            "updated_state_ids": list(result.updated_state_ids),
            "mastery_updated": True,
            "error": None,
        }

    return update_mastery_node


__all__ = ["build_update_mastery_node", "serialize_mastery_result"]
