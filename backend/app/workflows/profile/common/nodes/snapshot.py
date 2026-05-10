"""Profile read-only snapshot nodes.

These nodes assemble the data returned by Profile API overview calls. They do
not mutate mastery states, schedule reviews, or persist profile summaries.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import profile_repo
from app.schemas.profile import MasteryStateResponse
from app.workflows.profile.common.nodes.sessioning import node_session
from app.workflows.profile.common.state import ProfileWorkflowState


def _knowledge_unit_map(
    session: Session,
    *,
    course_id: str,
    knowledge_unit_ids: list[int],
) -> dict[int, KnowledgeUnit]:
    ids = sorted({knowledge_unit_id for knowledge_unit_id in knowledge_unit_ids if knowledge_unit_id > 0})
    if not ids:
        return {}
    units = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.course_id == course_id,
            KnowledgeUnit.id.in_(ids),
        )
    ).all()
    return {unit.id: unit for unit in units if unit.id is not None}


def _state_response(state, knowledge_unit: KnowledgeUnit | None = None) -> MasteryStateResponse:
    if state.knowledge_unit_id is None:
        raise ValueError("Encountered legacy unit-level mastery state.")
    return MasteryStateResponse(
        id=state.id,
        knowledge_unit_id=state.knowledge_unit_id,
        knowledge_unit_name=knowledge_unit.canonical_name if knowledge_unit is not None else None,
        knowledge_unit_type=knowledge_unit.knowledge_unit_type if knowledge_unit is not None else None,
        mastery_score=state.mastery_score,
        confidence_score=state.confidence_score,
        stability_score=state.stability_score,
        forgetting_due_at=state.forgetting_due_at,
        review_priority=state.review_priority,
        total_attempts=state.total_attempts,
        correct_attempts=state.correct_attempts,
        last_attempt_at=state.last_attempt_at,
        state_version=state.state_version,
        updated_at=state.updated_at,
    )


def build_load_mastery_overview_node(*, session: Session | None = None):
    """Build the read-only mastery overview node."""

    def load_mastery_overview_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        user_id = state.get("user_id")
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with node_session(session) as db_session:
                knowledge_unit_states = profile_repo.list_knowledge_states(
                    db_session,
                    user_id=user_id,
                    course_id=course_id,
                    target_kind="knowledge_unit",
                )
                knowledge_unit_by_id = _knowledge_unit_map(
                    db_session,
                    course_id=course_id,
                    knowledge_unit_ids=[
                        int(item.knowledge_unit_id)
                        for item in knowledge_unit_states
                        if item.knowledge_unit_id is not None
                    ],
                )
                response_items = [
                    _state_response(item, knowledge_unit_by_id.get(int(item.knowledge_unit_id)))
                    for item in knowledge_unit_states
                ]
        except Exception as exc:
            return {
                **state,
                "error": f"load_mastery_overview_failed:{exc}",
            }

        return {
            **state,
            "weak_knowledge_unit_count": sum(1 for item in knowledge_unit_states if item.mastery_score < 0.8),
            "knowledge_unit_states": [
                item.model_dump(mode="python") for item in response_items
            ],
            "error": None,
        }

    return load_mastery_overview_node


__all__ = ["build_load_mastery_overview_node"]
