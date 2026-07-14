"""Profile context resolution nodes.

These nodes validate the DB-backed identity for Profile graph runs. They do
not update mastery, schedule reviews, or build API response payloads.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models import Course, ExamPaper
from app.workflows.profile.common.lib.locking import (
    acquire_profile_user_lock,
    prepare_profile_write_transaction,
)
from app.workflows.profile.common.nodes.sessioning import node_session
from app.workflows.profile.common.state import ProfileWorkflowState


def _exam_context_error(
    state: ProfileWorkflowState,
    paper: ExamPaper | None,
) -> str | None:
    if paper is None:
        return f"exam_paper_not_found:{state['exam_paper_id']}"

    requested_course = state.get("course_id")
    if requested_course and requested_course != paper.course_id:
        return f"exam_paper_course_mismatch:{requested_course}!={paper.course_id}"

    requested_user_id = state.get("user_id")
    if requested_user_id and requested_user_id != paper.user_id:
        return f"exam_paper_user_mismatch:{requested_user_id}!={paper.user_id}"
    return None


def build_resolve_exam_profile_context_node(*, session: Session | None = None):
    """Resolve course and user ids from a graded exam paper."""

    def resolve_exam_profile_context(state: ProfileWorkflowState) -> ProfileWorkflowState:
        try:
            with node_session(session) as db_session:
                prepare_profile_write_transaction(db_session)
                paper = db_session.get(ExamPaper, state["exam_paper_id"])
                error = _exam_context_error(state, paper)
                if error is not None:
                    return {**state, "error": error}

                assert paper is not None
                locked_user_id = paper.user_id
                locked_course_id = paper.course_id
                acquire_profile_user_lock(db_session, user_id=locked_user_id)
                db_session.expire_all()

                paper = db_session.get(ExamPaper, state["exam_paper_id"])
                error = _exam_context_error(state, paper)
                if error is not None:
                    return {**state, "error": error}
                assert paper is not None
                if paper.user_id != locked_user_id or paper.course_id != locked_course_id:
                    return {
                        **state,
                        "error": f"exam_paper_context_changed:{state['exam_paper_id']}",
                    }

                return {
                    **state,
                    "course_id": paper.course_id,
                    "user_id": paper.user_id,
                    "error": None,
                }
        except Exception as exc:
            return {
                **state,
                "error": f"resolve_profile_context_failed:{exc}",
            }

    return resolve_exam_profile_context


def build_validate_profile_snapshot_context_node(*, session: Session | None = None):
    """Validate the course/user pair used by read-only Profile snapshots."""

    def validate_profile_snapshot_context(state: ProfileWorkflowState) -> ProfileWorkflowState:
        course_id = str(state.get("course_id") or "").strip()
        user_id = str(state.get("user_id") or "").strip()
        if not course_id or not user_id:
            return {
                **state,
                "error": "profile_snapshot_context_missing",
            }

        try:
            with node_session(session) as db_session:
                course = db_session.exec(
                    select(Course).where(Course.id == course_id, Course.user_id == user_id)
                ).first()
                if course is None:
                    return {
                        **state,
                        "error": f"profile_course_not_found:{course_id}",
                    }
        except Exception as exc:
            return {
                **state,
                "error": f"validate_profile_snapshot_context_failed:{exc}",
            }

        return {**state, "course_id": course_id, "user_id": user_id, "error": None}

    return validate_profile_snapshot_context


__all__ = [
    "build_resolve_exam_profile_context_node",
    "build_validate_profile_snapshot_context_node",
]
