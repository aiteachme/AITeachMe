"""Profile weakness analysis node.

This node ranks weak knowledge units from mastery and exam history. It keeps
serialization local to the graph boundary and leaves ranking logic in lib.
"""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.profile.common.lib.weakness import WeaknessItem, analyze_weakness
from app.workflows.profile.common.nodes.sessioning import node_session
from app.workflows.profile.common.state import ProfileWorkflowState


def serialize_weaknesses(items: list[WeaknessItem]) -> list[dict[str, object]]:
    """Convert weakness objects into JSON-friendly graph state."""

    return [
        {
            "knowledge_unit_id": item.knowledge_unit_id,
            "priority": item.priority,
            "reason": item.reason,
            "mastery_score": item.mastery_score,
            "recent_wrong_rate": item.recent_wrong_rate,
            "exam_weight": item.exam_weight,
        }
        for item in items
    ]


def build_analyze_weakness_node(*, session: Session | None = None):
    """Build the weak-knowledge ranking node."""

    def analyze_weakness_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        user_id = state.get("user_id")
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with node_session(session) as db_session:
                weaknesses = analyze_weakness(
                    db_session,
                    user_id=user_id,
                    course_id=course_id,
                    top_n=int(state.get("top_n") or 20),
                )
        except Exception as exc:
            return {
                **state,
                "error": f"analyze_weakness_failed:{exc}",
            }
        return {
            **state,
            "weaknesses": serialize_weaknesses(weaknesses),
            "weaknesses_ranked": True,
            "error": None,
        }

    return analyze_weakness_node


__all__ = ["build_analyze_weakness_node", "serialize_weaknesses"]
