"""Profile summary nodes for course and user snapshots.

The persisted refresh nodes are used after exam grading. The snapshot nodes
are read-only and serve Profile API overview calls.
"""

from __future__ import annotations

from sqlmodel import Session

from app.workflows.profile.pipeline.lib.course_profile import (
    build_course_profile_summary,
    refresh_course_profile_summary,
)
from app.workflows.profile.pipeline.lib.user_profile import (
    build_user_profile_summary,
    refresh_user_profile_summary,
)
from app.workflows.profile.pipeline.nodes.sessioning import node_session
from app.workflows.profile.pipeline.state import ProfileWorkflowState


def build_refresh_course_profile_node(*, session: Session | None = None):
    """Build the persisted course-profile refresh node."""

    def refresh_course_profile_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        if not course_id:
            return {
                **state,
                "error": "profile_course_missing",
            }

        try:
            with node_session(session) as db_session:
                summary = refresh_course_profile_summary(
                    db_session,
                    course_id=course_id,
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"refresh_course_profile_failed:{exc}",
            }
        return {
            **state,
            "course_profile": summary.model_dump(mode="python"),
            "error": None,
        }

    return refresh_course_profile_node


def build_refresh_user_profile_node(*, session: Session | None = None):
    """Build the persisted user-profile refresh node."""

    def refresh_user_profile_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        user_id = state.get("user_id")
        if not user_id:
            return {
                **state,
                "error": "profile_user_missing",
            }

        try:
            with node_session(session) as db_session:
                summary = refresh_user_profile_summary(
                    db_session,
                    user_id=user_id,
                    auto_commit=False,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"refresh_user_profile_failed:{exc}",
            }
        return {
            **state,
            "user_profile": summary.model_dump(mode="python"),
            "report_generated": True,
            "error": None,
        }

    return refresh_user_profile_node


def build_course_profile_snapshot_node(*, session: Session | None = None):
    """Build the read-only course-profile snapshot node."""

    def course_profile_snapshot_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = state.get("course_id")
        user_id = state.get("user_id")
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_context_missing",
            }

        try:
            with node_session(session) as db_session:
                summary = build_course_profile_summary(
                    db_session,
                    course_id=course_id,
                    user_id=user_id,
                )
        except Exception as exc:
            return {
                **state,
                "error": f"build_course_profile_snapshot_failed:{exc}",
            }
        return {
            **state,
            "course_profile": summary.model_dump(mode="python"),
            "error": None,
        }

    return course_profile_snapshot_node


def build_user_profile_snapshot_node(*, session: Session | None = None):
    """Build the read-only user-profile snapshot node."""

    def user_profile_snapshot_node(state: ProfileWorkflowState) -> ProfileWorkflowState:
        user_id = state.get("user_id")
        if not user_id:
            return {
                **state,
                "error": "profile_user_missing",
            }

        try:
            with node_session(session) as db_session:
                summary = build_user_profile_summary(db_session, user_id=user_id)
        except Exception as exc:
            return {
                **state,
                "error": f"build_user_profile_snapshot_failed:{exc}",
            }
        return {
            **state,
            "user_profile": summary.model_dump(mode="python"),
            "report_generated": True,
            "error": None,
        }

    return user_profile_snapshot_node


__all__ = [
    "build_course_profile_snapshot_node",
    "build_refresh_course_profile_node",
    "build_refresh_user_profile_node",
    "build_user_profile_snapshot_node",
]
