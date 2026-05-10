"""Profile study-plan graph node builders.

The nodes read existing profile summaries and derive a short execution plan.
They do not write DB rows or call Digest Planner.
"""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.profile.pipeline.lib.course_profile import build_course_profile_summary
from app.workflows.profile.pipeline.lib.user_profile import build_user_profile_summary
from app.workflows.profile.pipeline.nodes.sessioning import node_session
from app.workflows.profile.study_plan.lib import build_profile_study_plan
from app.workflows.profile.study_plan.state import ProfileStudyPlanState


def build_load_profile_context_node(*, session: Session | None = None):
    """Build the node that loads read-only profile summaries."""

    def load_profile_context_node(state: ProfileStudyPlanState) -> ProfileStudyPlanState:
        course_id = state.get("course_id")
        user_id = state.get("user_id")
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_study_plan_context_missing",
            }

        try:
            with node_session(session) as db_session:
                course_profile = build_course_profile_summary(
                    db_session,
                    course_id=course_id,
                    user_id=user_id,
                )
                user_profile = build_user_profile_summary(db_session, user_id=user_id)
        except Exception as exc:
            return {
                **state,
                "error": f"load_profile_study_plan_context_failed:{exc}",
            }

        return {
            **state,
            "course_profile": course_profile.model_dump(mode="python"),
            "user_profile": user_profile.model_dump(mode="python"),
            "error": None,
        }

    return load_profile_context_node


def build_study_plan_node():
    """Build the deterministic study-plan node."""

    def study_plan_node(state: ProfileStudyPlanState) -> ProfileStudyPlanState:
        try:
            study_plan = build_profile_study_plan(
                course_profile=state.get("course_profile"),
                user_profile=state.get("user_profile"),
            )
        except Exception as exc:
            return {
                **state,
                "error": f"build_profile_study_plan_failed:{exc}",
            }

        return {
            **state,
            "study_plan": study_plan,
            "error": None,
        }

    return study_plan_node


def fail_study_plan_node(state: ProfileStudyPlanState) -> ProfileStudyPlanState:
    """Return failed state unchanged for traceable graph completion."""

    return state


__all__ = [
    "build_load_profile_context_node",
    "build_study_plan_node",
    "fail_study_plan_node",
]
